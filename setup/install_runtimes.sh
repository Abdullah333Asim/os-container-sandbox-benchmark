#!/bin/bash
set -e

sudo apt update
sudo apt install -y \
  git build-essential curl wget ca-certificates gnupg \
  python3 python3-pip python3-psutil python3-matplotlib python3-pandas \
  docker.io containerd podman lxc lxc-templates uidmap containernetworking-plugins

sudo systemctl enable --now docker containerd
sudo usermod -aG docker "$USER"

NERDCTL_VER=$(curl -s https://api.github.com/repos/containerd/nerdctl/releases/latest | grep -oP '"tag_name": "v\K[^"]+')
wget -q "https://github.com/containerd/nerdctl/releases/download/v${NERDCTL_VER}/nerdctl-${NERDCTL_VER}-linux-amd64.tar.gz"
sudo tar -C /usr/local/bin -xzf "nerdctl-${NERDCTL_VER}-linux-amd64.tar.gz" nerdctl
rm -f "nerdctl-${NERDCTL_VER}-linux-amd64.tar.gz"

curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list > /dev/null
sudo apt update && sudo apt install -y runsc
sudo runsc install
sudo systemctl restart docker

echo "Install complete. Reboot once so docker group & rootless podman apply cleanly."
