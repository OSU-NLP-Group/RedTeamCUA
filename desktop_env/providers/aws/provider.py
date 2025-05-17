import boto3
from botocore.exceptions import ClientError,WaiterError

import logging

from desktop_env.providers.base import Provider

import time
from desktop_env.providers.aws.aws_config import IMAGE_ID_MAP,INSTANCE_TYPE,NETWORK_INTERFACE_MAP,BLOCK_DEVICE_MAPPINGS


logger = logging.getLogger("desktopenv.providers.aws.AWSProvider")
logger.setLevel(logging.INFO)

WAIT_DELAY = 15
MAX_ATTEMPTS = 10

def wait_for_status_checks(ec2_client, instance_id, max_attempts=40):
    for check_count in range(1, max_attempts + 1):
        RETRY_TIMES = 5
        RETRY_DELAY = 5 
        CHECK_INTERVAL = 10
        for attempt in range(1, RETRY_TIMES + 1):
            try:
                status_resp = ec2_client.describe_instance_status(InstanceIds=[instance_id])
                break 
            except Exception as e:
                logger.error(f"[Describe Attempt {attempt}/{RETRY_TIMES}] "
                             f"Failed to describe status for {instance_id}: {e}")
                if attempt < RETRY_TIMES:
                    logger.info(f"Retrying describe_instance_status in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(f"All {RETRY_TIMES} describe attempts failed. Giving up.")
                    return False

        statuses = status_resp.get('InstanceStatuses', [])
        if statuses and statuses[0]['SystemStatus']['Status'] == 'ok':
            logger.info(f"Instance {instance_id} passed system status check.")
            return True

        logger.info(
            f"Checking system status of {instance_id} ({check_count}/{max_attempts}) — "
            f"still initializing, will check again in {CHECK_INTERVAL}s."
        )
        time.sleep(CHECK_INTERVAL)

    logger.warning(f"Instance {instance_id} did not pass status checks after {max_attempts} attempts.")
    return False




class AWSProvider(Provider):

    def start_emulator(self, path_to_vm: str, headless: bool):
        RETRY_TIMES = 5 
        RETRY_DELAY = 5
        WAIT_DELAY = 10
        MAX_ATTEMPTS = 30

        logger.info("Starting AWS VM...")
        ec2_client = boto3.client('ec2', region_name=self.region)

        for attempt in range(1, RETRY_TIMES + 1):
            try:
                response = ec2_client.describe_instances(InstanceIds=[path_to_vm])
                if response['Reservations'] and response['Reservations'][0]['Instances']:
                    current_state = response['Reservations'][0]['Instances'][0]['State']['Name']
                    if current_state in ['shutting-down', 'terminated']:
                        raise Exception(f"Cannot start instance {path_to_vm}. Current state: {current_state}")

                ec2_client.start_instances(InstanceIds=[path_to_vm])
                logger.info(f"[Attempt {attempt}] Instance {path_to_vm} is starting...")

                waiter = ec2_client.get_waiter('instance_running')
                try:
                    waiter.wait(
                        InstanceIds=[path_to_vm],
                        WaiterConfig={'Delay': WAIT_DELAY, 'MaxAttempts': MAX_ATTEMPTS}
                    )
                    logger.info(f"Instance {path_to_vm} is now running.")
                    return
                except WaiterError as we:
                    msg = str(we)
                    if "shutting-down" in msg or "terminated" in msg:
                        raise Exception(f"Instance {path_to_vm} entered '{msg}' and cannot be started")
                    else:
                        raise

            except (ClientError, WaiterError, Exception) as e:
                logger.error(f"[Attempt {attempt}] Failed to start AWS VM {path_to_vm}: {e}")
                if attempt < RETRY_TIMES:
                    logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(f"All {RETRY_TIMES} attempts failed. Giving up.")
                    raise

    def get_ip_address(self, path_to_vm: str) -> str:
        logger.info("Getting AWS VM IP address...")
        ec2_client = boto3.client('ec2', region_name=self.region)

        try:
            response = ec2_client.describe_instances(InstanceIds=[path_to_vm])
            for reservation in response['Reservations']:

                for instance in reservation['Instances']:
                    # private_ip_address = instance.get('PrivateIpAddress', '')
                    # return private_ip_address
                    ip = instance.get('PublicIpAddress', '')
                    return ip
            return ''  # Return an empty string if no IP address is found
        except Exception as e:
            logger.error(f"Failed to retrieve private IP address for the instance {path_to_vm}: {str(e)}")
            raise


    def save_state(self, path_to_vm: str, snapshot_name: str):
        logger.info("Saving AWS VM state...")
        ec2_client = boto3.client('ec2', region_name=self.region)

        try:
            image_response = ec2_client.create_image(InstanceId=path_to_vm, ImageId=snapshot_name)
            image_id = image_response['ImageId']
            logger.info(f"AMI {image_id} created successfully from instance {path_to_vm}.")
            return image_id
        except Exception as e:
            logger.error(f"Failed to create AMI from the instance {path_to_vm}: {str(e)}")
            raise

    def revert_to_snapshot(self, path_to_vm: str, snapshot_name: str):
        ec2_client = boto3.client('ec2', region_name=self.region)

        try:
            RETRY_TIMES = 5
            RETRY_DELAY = 20
            WAIT_DELAY = 15  # seconds between checks
            MAX_ATTEMPTS = 20  # max waiter attempts
            
            for attempt in range(1, RETRY_TIMES + 1):
                try:
                    run_instances_params = {
                        "MaxCount": 1,
                        "MinCount": 1,
                        "ImageId": IMAGE_ID_MAP[self.region][self.aws_ami],
                        "InstanceType": INSTANCE_TYPE[self.aws_ami],
                        "EbsOptimized": True,
                        "NetworkInterfaces": NETWORK_INTERFACE_MAP[self.region],
                        "BlockDeviceMappings": BLOCK_DEVICE_MAPPINGS[self.aws_ami],
                        "TagSpecifications": [
                            {
                                "ResourceType": "instance",
                                "Tags": [
                                    {"Key": "Name", "Value": "RedTeamCUA"}
                                ]
                            }
                        ]
                    }
                    new_instance = ec2_client.run_instances(**run_instances_params)
                    new_instance_id = new_instance['Instances'][0]['InstanceId']
                    logger.info(f"New instance {new_instance_id} launched from snapshot {snapshot_name}.")
                    logger.info(f"Waiting for instance {new_instance_id} to be running...")

                    ec2_client.get_waiter('instance_running').wait(
                        InstanceIds=[new_instance_id],
                        WaiterConfig={'Delay': WAIT_DELAY, 'MaxAttempts': MAX_ATTEMPTS}
                    )

                    wait_for_status_checks(ec2_client, new_instance_id)
                    
                    logger.info(f"Instance {new_instance_id} is ready.")
                    return new_instance_id

                except Exception as e:
                    logger.error(f"[Attempt {attempt}] Failed to launch AWS VM from snapshot {snapshot_name}: {e}")
                    if attempt < RETRY_TIMES:
                        logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.error(f"All {RETRY_TIMES} attempts to launch instance failed. Giving up.")
                        raise

            return new_instance_id

        except Exception as e:
            logger.error(f"Failed to revert to snapshot {snapshot_name} for the instance {path_to_vm}: {str(e)}")
            raise
        
            
    def terminate_emulator(self, instance_id, region=None):
        RETRY_TIMES = 5
        RETRY_DELAY = 20
        WAIT_DELAY = 15  # seconds between checks
        MAX_ATTEMPTS = 20  # max waiter attempts
        
        logger.info(f"Terminating AWS VM {instance_id} in region {self.region}...")
        ec2_client = boto3.client('ec2', region_name=self.region)
        
        for attempt in range(1, RETRY_TIMES + 1):
            try:
                ec2_client.terminate_instances(InstanceIds=[instance_id])
                waiter = ec2_client.get_waiter('instance_terminated')
                waiter.wait(
                    InstanceIds=[instance_id],
                    WaiterConfig={'Delay': WAIT_DELAY, 'MaxAttempts': MAX_ATTEMPTS}
                )
                logger.info(f"Instance {instance_id} has been terminated.")
                return
            
            except Exception as e:
                logger.error(f"[Attempt {attempt}] Failed to terminate AWS VM {instance_id}: {e}")
                if attempt < RETRY_TIMES:
                    logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(f"All {RETRY_TIMES} attempts failed. Giving up.")
                    raise

    def stop_emulator(self, path_to_vm, region=None):
        RETRY_TIMES = 5
        RETRY_DELAY = 20
        logger.info(f"Stopping AWS VM {path_to_vm}...")
        ec2_client = boto3.client('ec2', region_name=self.region)
        
        for attempt in range(1, RETRY_TIMES + 1):
            
            try:
                ec2_client.stop_instances(InstanceIds=[path_to_vm])
                waiter = ec2_client.get_waiter('instance_stopped')
                waiter.wait(InstanceIds=[path_to_vm], WaiterConfig={'Delay': WAIT_DELAY, 'MaxAttempts': MAX_ATTEMPTS})
                logger.info(f"Instance {path_to_vm} has been stopped.")
                return
            
            except Exception as e:
                logger.error(f"[Attempt {attempt}] Failed to stop AWS VM {path_to_vm}: {e}")
                if attempt < RETRY_TIMES:
                    logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(f"All {RETRY_TIMES} attempts failed. Giving up.")
                    raise