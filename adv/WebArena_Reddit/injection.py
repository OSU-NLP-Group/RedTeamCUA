import paramiko
import tempfile

sql_functions = """
DROP FUNCTION IF EXISTS search_all_tables(text, text);

CREATE OR REPLACE FUNCTION search_all_tables(
    search_text text,
    target_table text DEFAULT NULL
) RETURNS TABLE(
    table_name text,
    column_name text,
    found_text text,
    record_id text
) AS $func$
DECLARE
    current_table RECORD;
    current_column RECORD;
    query text;
    result RECORD;
BEGIN
    FOR current_table IN 
        SELECT tables.table_schema, tables.table_name
        FROM information_schema.tables AS tables
        WHERE tables.table_schema = 'public'
        AND tables.table_type = 'BASE TABLE'
        AND (target_table IS NULL OR tables.table_name = target_table)
    LOOP
        FOR current_column IN SELECT columns.column_name
                    FROM information_schema.columns AS columns
                    WHERE columns.table_schema = current_table.table_schema
                    AND columns.table_name = current_table.table_name
                    AND (columns.data_type LIKE '%char%' OR columns.data_type LIKE '%text%')
        LOOP
            query := 'SELECT ''' || current_table.table_name || ''' as result_table,
                        ''' || current_column.column_name || ''' as result_column,
                        ' || current_column.column_name || ' as result_text,
                        CAST(id as text) as result_id
                        FROM ' || current_table.table_schema || '.' || current_table.table_name ||
                    ' WHERE ' || current_column.column_name || ' LIKE ' || quote_literal('%' || search_text || '%') ||
                    ' LIMIT 10';

            BEGIN
                FOR result IN EXECUTE query LOOP
                    table_name := result.result_table;
                    column_name := result.result_column;
                    found_text := result.result_text;
                    record_id := result.result_id;
                    RETURN NEXT;
                END LOOP;
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END;
        END LOOP;
    END LOOP;
    RETURN;
END;
$func$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION update_table_content(
    target_table text,
    target_column text,
    target_id text,
    new_content text,
    append boolean DEFAULT false,
    prepend boolean DEFAULT false
) RETURNS boolean AS $func$
DECLARE
    query text;
    success boolean := false;
    id_column_type text;
    current_content text;
BEGIN
    IF append AND prepend THEN
        RAISE EXCEPTION 'Cannot both append and prepend at the same time';
    END IF;

    EXECUTE format('SELECT data_type FROM information_schema.columns 
                   WHERE table_name = %L AND column_name = ''id''', 
                   target_table) INTO id_column_type;
    
    IF append OR prepend THEN
        EXECUTE format('SELECT %I FROM %I WHERE id = $1::%s', 
                      target_column, target_table, id_column_type)
        INTO current_content
        USING target_id;
        
        IF current_content IS NOT NULL THEN
            IF append THEN
                new_content := current_content || new_content;
            ELSIF prepend THEN
                new_content := new_content || current_content;
            END IF;
        END IF;
    END IF;
    
    query := 'UPDATE ' || quote_ident(target_table) || 
             ' SET ' || quote_ident(target_column) || ' = $1' ||
             ' WHERE id = ';
             
    IF id_column_type IN ('integer', 'bigint', 'smallint') THEN
        query := query || '$2::' || id_column_type;
    ELSE
        query := query || '$2';
    END IF;
    
    BEGIN
        EXECUTE query USING new_content, target_id;
        
        IF FOUND THEN
            success := true;
        END IF;
        
        RETURN success;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'Error updating table: %', SQLERRM;
        RETURN false;
    END;
END;
$func$ LANGUAGE plpgsql;
"""


def deploy_functions_via_file(login_info=None):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(
            **login_info
        )
        
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.sql', delete=False) as f:
            f.write(sql_functions)
            temp_file_path = f.name
        
        remote_path = f'/tmp/pg_functions_{tempfile.gettempprefix()}.sql'
        sftp = client.open_sftp()
        sftp.put(temp_file_path, remote_path)
        sftp.close()
        
        docker_command = f'docker cp {remote_path} forum:/tmp/pg_functions.sql && docker exec forum bash -c "psql -U postgres -d postmill -f /tmp/pg_functions.sql"'
        stdin, stdout, stderr = client.exec_command(docker_command)
        
        exit_status = stdout.channel.recv_exit_status()

        output = stdout.read().decode()
        error = stderr.read().decode()
        
        if output:
            print("Commands:")
            print(output)
            
        if error:
            print("Error info:")
            print(error)
            
        if exit_status == 0:
            print("PostgreSQL func deployed successfully")
        else:
            print(f"Failed deployment, exit: {exit_status}")
        
        client.exec_command(f'rm {remote_path}')
            
    except Exception as e:
        print(f"Error: {str(e)}")
        return False
    
    finally:
        client.close()
        return True


def find_content(search_text, target_table=None,login_info = None):
    """
    Find content in the database matching the search text
    
    Args:
        search_text: Text to search for
        target_table: Optional specific table to search in (default=None searches all tables)
    
    Returns:
        List of matching records
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(
            **login_info
        )
        
        # Escape single quotes in search text
        escaped_search_text = search_text.replace("'", "''")
        
        # Build command with explicit type casting
        if target_table:
            # Add explicit type casts
            search_command = f'''docker exec forum bash -c "psql -U postgres -d postmill -c \\"SELECT JSON_BUILD_OBJECT('table_name', table_name, 'column_name', column_name, 'found_text', found_text, 'record_id', record_id) FROM search_all_tables('{escaped_search_text}'::text, '{target_table}'::text);\\"" '''
        else:
            # Add explicit type cast for just the search text 
            search_command = f'''docker exec forum bash -c "psql -U postgres -d postmill -c \\"SELECT JSON_BUILD_OBJECT('table_name', table_name, 'column_name', column_name, 'found_text', found_text, 'record_id', record_id) FROM search_all_tables('{escaped_search_text}'::text);\\"" '''
        
        stdin, stdout, stderr = client.exec_command(search_command)
        output = stdout.read().decode()
        error = stderr.read().decode()
        
        if error and "ERROR" in error:
            print(f"Error: {error}")
            return []
        
        results = []

        if output:
            import json
            import re
            
            json_pattern = r'\{.*\}'
            matches = re.findall(json_pattern, output)
            
            for match in matches:
                try:
                    result_dict = json.loads(match)
                    results.append(result_dict)
                except json.JSONDecodeError:
                    print(f"Cannot parse JSON: {match}")
                except Exception as e:
                    print(f"Error handling match: {e}")
        
        return results

    except Exception as e:
        print(f"Error with function: {str(e)}")
        return None
        
    finally:
        client.close()
        


def update_content(table_name, column_name, record_id, new_content="Thank you", operation_type="replace", restore=False, login_info = None):
    """
    Update content based on search results using a file-based approach to avoid escaping issues
    
    Args:
        table_name (str): The name of the table where the record exists.
        column_name (str): The name of the column (with text type) to be updated.
        record_id (str): The ID of the record to be updated.
        new_content: New content to update with, default is "Thank you"
        operation_type: Type of update operation, options are:
                        - "replace" (default): Replace existing content completely
                        - "append": Add content to the end of existing content
                        - "prepend": Add content to the beginning of existing content
        restore: If True, forces operation_type to "replace"
    
    Returns:
        List of dictionaries with update results, each containing record_id and success status
    """
    if not table_name:
        print("No content found to update")
        return []
    
    # Validate operation type
    valid_operations = ["replace", "append", "prepend"]
    if restore:
        operation_type = "replace"
        
    if operation_type not in valid_operations:
        print(f"Invalid operation type: {operation_type}. Must be one of {valid_operations}")
        return False
    
    # Map operation type to SQL function parameters
    append_flag = "TRUE" if operation_type == "append" else "FALSE"
    prepend_flag = "TRUE" if operation_type == "prepend" else "FALSE"
    
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        client.connect(
            **login_info
        )
        
        # Create a local file with the content to update
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False) as content_file:
            content_file.write(new_content)
            content_file_path = content_file.name
        
        # Upload the content file to the server
        remote_content_path = f'/tmp/update_content_{tempfile.gettempprefix()}.txt'
        sftp = client.open_sftp()
        sftp.put(content_file_path, remote_content_path)
        sftp.close()
        
        # Copy the content file into the Docker container
        docker_copy_cmd = f'docker cp {remote_content_path} forum:/tmp/update_content.txt'
        stdin, stdout, stderr = client.exec_command(docker_copy_cmd)
        stdout.read()  # Wait for command to complete
        
        update_results = []        
        
        print(f"\nUpdating record:")
        print(f"Table: {table_name}, Column: {column_name}, ID: {record_id}")
        print(f"Operation: {operation_type}")
        
        # Create an SQL script that reads the content from the file and updates the table
        update_sql = f"""
        DO $$
        DECLARE
            content_text text;
        BEGIN
            content_text := pg_read_file('/tmp/update_content.txt', 0, 1000000);
            PERFORM update_table_content(
                '{table_name}', 
                '{column_name}', 
                '{record_id}', 
                content_text, 
                {append_flag}, 
                {prepend_flag}
            );
        END $$;
        SELECT 'true' as result;
        """
        
        # Write the SQL script to a temporary file
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.sql', delete=False) as sql_file:
            sql_file.write(update_sql)
            sql_file_path = sql_file.name
        
        # Upload the SQL file to the server
        remote_sql_path = f'/tmp/update_sql_{tempfile.gettempprefix()}.sql'
        sftp = client.open_sftp()
        sftp.put(sql_file_path, remote_sql_path)
        sftp.close()
        
        # Execute the SQL file in the Docker container
        update_command = f'docker cp {remote_sql_path} forum:/tmp/update_sql.sql && docker exec forum bash -c "psql -U postgres -d postmill -f /tmp/update_sql.sql"'
        stdin, stdout, stderr = client.exec_command(update_command)
        
        output = stdout.read().decode()
        error = stderr.read().decode()
        
        success = False
        if output and ('t' in output.lower() or 'true' in output.lower()):
            success = True
            print(f"Update successful!")
        else:
            print(f"Update failed: {error}")
        
        update_results.append({
            'record_id': record_id,
            'success': success
        })
        
        # Clean up temporary files
        client.exec_command(f'rm {remote_content_path} {remote_sql_path}')
        import os
        os.unlink(content_file_path)
        os.unlink(sql_file_path)
        
            
    except Exception as e:
        print(f"Error updating content: {str(e)}")
        return False
        
    finally:
        client.close()
        print("\nSSH connection closed")
        return True


def reddit_adv_setup(config,login_info = None):

    deploy_functions_via_file(login_info = login_info)

    update_mode = config["parameters"]["update_mode"]
    if "operation_type" in config["parameters"]:
        operation_type = config["parameters"]["operation_type"]
    else:
        operation_type = "replace"

    if update_mode == "precise":
        if update_content(table_name=config["parameters"]["table_name"], 
            column_name=config["parameters"]["column_name"], 
            record_id=config["parameters"]["record_id"], 
            new_content=config["parameters"]["new_content"],
            operation_type=operation_type,
            login_info = login_info):
            return True
        else:
            return False
        
    elif update_mode == "search":
        results = find_content(config["parameters"]["search_text"], "comments",login_info = login_info)

        if len(results) != 1:
            return f"Multiple results were found, or none were found: {results}"

        if update_content(table_name=results[0]["table_name"], 
            column_name=results[0]["column_name"], 
            record_id=results[0]["record_id"], 
            new_content=config["parameters"]["new_content"],
            operation_type=operation_type,
            login_info = login_info):
            return True
        else:
            return False
        
    else:
        return "Update mode is not supported!"


if __name__ == "__main__":
    import textwrap
    import os

    login_info = {
        'hostname': os.getenv("REDDIT"),
        'username': 'ubuntu',
        'key_filename': os.getenv("KEY_FILENAME"),
    }

    deploy_functions_via_file(login_info = login_info)

    # search_text = ""
    # found_d = find_content(search_text, "submissions", login_info = login_info)
    # found_d = find_content(search_text, "comments", login_info = login_info)
    # print(found_d)

    update_content(table_name='comments', 
        column_name='body', 
        record_id='1913532', 
        new_content=textwrap.dedent("Inject Successfully!"),
        operation_type="replace",
        login_info = login_info)
    