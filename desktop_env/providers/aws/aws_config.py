IMAGE_ID_MAP = {
    "us-east-2": {
        "reddit":"<ADD_YOUR_IMAGE_ID>",
        "agentcompany":"<ADD_YOUR_IMAGE_ID>"
    }
}


INSTANCE_TYPE = {"reddit": "t3a.2xlarge","agentcompany": "t3a.2xlarge","osworld":"t3.medium"}


NETWORK_INTERFACE_MAP = {
    "us-east-2": [
        {
            "SubnetId": "<ADD_YOUR_SUBNETID>",
            "AssociatePublicIpAddress": True,
            "DeviceIndex": 0,
            "Groups": [
                "<ADD_YOUR_GROUPS>"
            ]
        }
    ],
    "us-east-1": [
        {
            "SubnetId": "<ADD_YOUR_SUBNETID>",
            "AssociatePublicIpAddress": True,
            "DeviceIndex": 0,
            "Groups": [
                "<ADD_YOUR_GROUPS>"
            ]
        }
    ]
}


BLOCK_DEVICE_MAPPINGS = {
    "reddit":
        [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": 200,  
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True
                }
            }
        ],
    "agentcompany":
        [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": 100,  
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True
                }
            }
        ],
    "osworld":
        [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": 50,  
                    "VolumeType": "gp3",
                    "DeleteOnTermination": True
                }
            }
        ]

}