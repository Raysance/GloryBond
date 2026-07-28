#!/bin/bash
# deploy_runner.sh
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

mkdir -p log

RUNNER_TRACKING_ID=0 nb run > log/run.log 2>&1
