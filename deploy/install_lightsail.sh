#!/usr/bin/env bash
set -euo pipefail
APP_DIR=/home/ubuntu/SFCD4
DATA_DIR=/home/ubuntu/sfcd-data
sudo apt update
sudo apt install -y python3-pip python3-venv nginx git
mkdir -p "$DATA_DIR"
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
sudo cp deploy/sfcd.service /etc/systemd/system/sfcd.service
sudo cp deploy/nginx-sfcd.conf /etc/nginx/sites-available/sfcd
sudo ln -sfn /etc/nginx/sites-available/sfcd /etc/nginx/sites-enabled/sfcd
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now sfcd
sudo systemctl restart nginx
echo "SFCD4 installed."
