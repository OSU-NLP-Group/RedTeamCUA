import os
import paramiko
import time

def owncloud_adv_setup(config, login_info = None):
    docker_container = 'owncloud'
    local_file_path = config["parameters"]["local_file_path"]
    docker_path = config["parameters"]["docker_path"]
    
    if not os.path.exists(local_file_path):
        print(f"Error: Local file {local_file_path} does not exist")
        return False
        
    # Create SSH client
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        print(f"Connecting to {login_info['hostname']}")
        client.connect(
            **login_info
        )
        
        sftp = client.open_sftp()
        
        temp_path = f"/tmp/{os.path.basename(local_file_path)}"
        sftp.put(local_file_path, temp_path)
        
        # Copy file from EC2 to Docker container
        print(f"Copying file to Docker container '{docker_container}'...")
        docker_cp_command = f'docker cp "{temp_path}" {docker_container}:"{docker_path}"'
        stdin, stdout, stderr = client.exec_command(docker_cp_command)
                
        # Wait for command to complete
        exit_status = stdout.channel.recv_exit_status()
        
        # Check for errors
        error = stderr.read().decode()
        if error or exit_status != 0:
            print(f"Error copying to Docker container: {error}")
            return False
            
        # Clean up temporary file on EC2 instance
        print("Cleaning up temporary files...")
        client.exec_command(f"rm {temp_path}")
        
        # Execute file scan command in Docker container
        print("Executing file scan command in Docker container...")
        # Remove -it parameters as this is a non-interactive environment
        scan_command = f'docker exec {docker_container} bash -c "cd /var/www/html && su -s /bin/bash www-data -c \\"php occ files:scan --all\\""'
        stdin, stdout, stderr = client.exec_command(scan_command)
        
        print("Waiting for scan command to complete...")
        # Check output periodically to see real-time progress
        while not stdout.channel.exit_status_ready():
            if stdout.channel.recv_ready():
                output = stdout.channel.recv(1024).decode('utf-8')
                print(output, end='')
            time.sleep(1)
        
        # Make sure to read all remaining output
        remaining_output = stdout.read().decode()
        if remaining_output:
            print(remaining_output)
        
        # Get command exit status
        exit_status = stdout.channel.recv_exit_status()
        
        # Check if command executed successfully
        scan_error = stderr.read().decode()
        if scan_error or exit_status != 0:
            print(f"Error executing scan command (exit status: {exit_status}): {scan_error}")
            return False
        
        print(f"Successfully uploaded {local_file_path} to {docker_container}:{docker_path} and executed scan command")
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        return False
        
    finally:
        # Close connections
        if 'sftp' in locals():
            sftp.close()
        client.close()
        return True
    


def owncloud_add_user(login_info=None):
    docker_container = "owncloud"
    username        = 'newuser'
    password        = 'SuperSecret123!'
    display_name    = 'Peter'

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print(f"Connecting to {login_info['hostname']} …")
        client.connect(**login_info)

        docker_cmd = (
            f'docker exec -u www-data -w /var/www/html {docker_container} '
            f'bash -c "OC_PASS=\'{password}\' '
            f'php occ user:add {username} --password-from-env --display-name=\'{display_name}\'"'
        )

        print("Executing:", docker_cmd)
        stdin, stdout, stderr = client.exec_command(docker_cmd)

        while not stdout.channel.exit_status_ready():
            if stdout.channel.recv_ready():
                print(stdout.channel.recv(1024).decode('utf-8'), end='')
        print(stdout.read().decode(), end='')

        exit_status = stdout.channel.recv_exit_status()
        err_text    = stderr.read().decode()

        if exit_status == 0 and not err_text:
            print(f"✅  User {username} created successfully")
            return True
        else:
            print(f"❌  Failed (exit {exit_status}): {err_text}")
            return False

    except Exception as e:
        print("❌  Error:", str(e))
        return False
    finally:
        client.close()



if __name__ == "__main__":

    login_info = {
        'hostname': os.getenv("OWNCLOUD"),
        'username': 'ubuntu',
        'key_filename': os.getenv("KEY_FILENAME")
    }

    owncloud_adv_setup(
        {
            "type": "owncloud_adv_setup",
            "parameters": {
                "local_file_path": "adv/TheAgentCompany_OwnCloud/file_to_upload/setup_project/Availability/disk/setup_project_disk_file_code.pdf",
                "docker_path": "/var/www/html/data/theagentcompany/files/shared_setup_project.pdf"
            },
        },
        login_info=login_info
    )
    
    owncloud_add_user(login_info)