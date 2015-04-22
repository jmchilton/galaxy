#!/bin/sh
$headers
$slots_statement
export GALAXY_SLOTS
$add_galaxy_to_path
$env_setup_commands
$instrument_pre_commands
cd $working_directory
$command
echo $? > $exit_code_path
$instrument_post_commands
