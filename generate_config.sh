### normal config generation
rm -f evaluation_examples/test_all_owncloud.json
rm -f evaluation_examples/test_all_reddit.json
rm -f evaluation_examples/test_all_rocketchat.json

python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_setup_project.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_setup_project.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_linux_tutorial.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_linux_tutorial.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_docker_entry.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_docker_entry.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_gitclone.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_gitclone.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_alias_tmux.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_alias_tmux.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_install_termcolor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_install_termcolor.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_git_config.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_git_config.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_install_nodejs.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_install_nodejs.json" --output_path "evaluation_examples"
python generate_config.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_vim_editor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_vim_editor.json" --output_path "evaluation_examples"



### config generation for end2end task
# rm -f evaluation_examples/test_all_owncloud_for_end2end.json
# rm -f evaluation_examples/test_all_reddit_for_end2end.json
# rm -f evaluation_examples/test_all_rocketchat_for_end2end.json

# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_setup_project.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_setup_project.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_linux_tutorial.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_linux_tutorial.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_docker_entry.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_docker_entry.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_gitclone.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_gitclone.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_alias_tmux.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_alias_tmux.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_install_termcolor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_install_termcolor.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_git_config.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_git_config.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_install_nodejs.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_install_nodejs.json" --output_path "evaluation_examples"
# python generate_config_for_end2end_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_vim_editor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_vim_editor.json" --output_path "evaluation_examples"



### config generation for pointer only task
# rm -f evaluation_examples/test_all_owncloud_for_pointer.json
# rm -f evaluation_examples/test_all_reddit_for_pointer.json
# rm -f evaluation_examples/test_all_rocketchat_for_pointer.json

# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_setup_project.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_setup_project.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_linux_tutorial.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_linux_tutorial.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_docker_entry.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_docker_entry.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_gitclone.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_gitclone.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_alias_tmux.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_alias_tmux.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_install_termcolor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_install_termcolor.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_git_config.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_git_config.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_install_nodejs.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_install_nodejs.json" --output_path "evaluation_examples"
# python generate_config_for_pointer_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_vim_editor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_vim_editor.json" --output_path "evaluation_examples"



### config generation for defense task
# rm -f evaluation_examples/test_all_owncloud_for_defense.json
# rm -f evaluation_examples/test_all_reddit_for_defense.json
# rm -f evaluation_examples/test_all_rocketchat_for_defense.json

# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_setup_project.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_setup_project.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_linux_tutorial.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_linux_tutorial.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_owncloud_docker_entry.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_owncloud_docker_entry.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_gitclone.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_gitclone.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_alias_tmux.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_alias_tmux.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_reddit_install_termcolor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_reddit_install_termcolor.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_git_config.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_git_config.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_install_nodejs.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_install_nodejs.json" --output_path "evaluation_examples"
# python generate_config_for_defense_test.py --benign_task_raw "goals/benign/benign_task.raw_own_rocketchat_vim_editor.json" --adversary_task_raw "goals/adv/adversary_task.raw_own_rocketchat_vim_editor.json" --output_path "evaluation_examples"
