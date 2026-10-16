#!/bin/bash
# Runs during every Cloudera AI model build: the endpoint (serve/predict.py) needs only the slim
# serving set; the jobs install requirements.txt themselves (mcc-00-sync-code).
pip3 install -r requirements-model.txt
