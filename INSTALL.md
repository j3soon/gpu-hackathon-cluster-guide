# Installation Guide

> This installation guide is intended for cluster administrators (for setting up the DGX A100 environment). For user instructions, please see the [README](README.md).

This guide describes the simplest way to set up a Docker-based environment for hackathon participants who are familiar with SSH and Docker. No prior experience with Slurm or Singularity is required. The goal is to provide each team with an isolated, customizable environment with minimal effort on the cluster admin's side. If you need a production-level cluster setup or require job scheduling, please refer to the Slurm documentation (and consider integrating Singularity/Apptainer or Pyxis/Enroot for container support).

## Prerequisites

- Machines with NVIDIA GPUs (e.g. DGX A100 x2)
- A user account and password with sudo privileges on each machine
- An open port assigned to each container (for example, 30001–30010 if running 10 containers), and ensure these ports are open in the firewall

## Local Environment Setup

- Clone the Repository:
  ```sh
  git clone --recurse-submodules https://github.com/j3soon/gpu-hackathon-cluster-guide.git
  cd gpu-hackathon-cluster-guide
  ```
- Python Environment  
  Install latest `uv` and create a virtual environment
  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  uv venv --python 3.12
  source .venv/bin/activate
  ```
- Ansible Environment  
  Install latest Ansible
  ```sh
  sudo apt update
  sudo apt install software-properties-common
  sudo add-apt-repository --yes --update ppa:ansible/ansible
  sudo apt install ansible
  ```

## Network Setup

For simplicity, we do not assume a high-speed network connection between cluster nodes.

Configure SSH server, copy SSH public key, edit SSH config, and test ports:

1. If the SSH server is not configured on some nodes, see [OpenSSH Server Setup](https://tutorial.j3soon.com/remote-development/openssh-server/) to configure it.

2. [Add your SSH public key](https://tutorial.j3soon.com/remote-development/openssh-server/#copy-ssh-public-key) to each node to enable passwordless SSH access. The easiest way to do this is by running `ssh-copy-id <user>@<ip>` from your local machine for each cluster node.

3. After that, [edit your local SSH config](https://tutorial.j3soon.com/remote-development/openssh-server/#set-up-ssh-config) to enable quick SSH access for each node with `ssh <hostname>`.

4. Check that required ports are open using `nc`. On the target node, run `nc -lvp <port>`. On local machine, send a test message: `echo hello | nc <ip> <port>`, and observe the message on the node. If `nc` is not installed, install it with `sudo apt install -y netcat-openbsd`.

Setup `playbooks/inventory` by filling out the hostnames under the `[nodes]` section. You can generate a template by running `python compile.py`, which will create a placeholder inventory file for you.

Gather per-cluster information for later post-hackathon clean up.

```sh
rm -rf playbooks/nodes/output
ansible-playbook -i playbooks/inventory playbooks/nodes/01-gather-pre-hackathon-info.yaml
```

## Storage Setup

For simplicity, we do not require a shared storage setup across cluster nodes.

On each node, choose a local storage location suitable for Docker data and team files. Preferably, use an NVMe SSD with at least 1TB of available space. Optionally, for higher performance and capacity, consider a SSD RAID 0 array with multiple SSDs, totaling up to 10–20TB storage space or more. Consider using `lsblk` or `df -h` to check available disks and space.

Next, create a symbolic link (`symlink`) in your home directory that points to the chosen storage location for convenient access. By default, the storage directory is `/raid/j3soon` and it will be linked as `~/j3soon`. If you wish to use a different location, modify the `data_storage_path` and `data_symlink_path` variables in the `playbooks/inventory` file. Each node can have a different storage location by per-node variables.

```sh
ansible-playbook -i playbooks/inventory playbooks/nodes/02-setup-data-storage.yaml --ask-become-pass
```

## Docker Setup

For each node, install Docker and NVIDIA Container Toolkit. The playbook below will also configure Docker to use the specified data root directory for storage. By default, this directory is set to `/raid/docker-root-A100`, but you can change it by updating the `docker_data_root` variable in the `playbooks/inventory` file.

```sh
# Install/Upgrade Docker and NVIDIA Container Toolkit, can be skipped if already installed.
ansible-playbook -i playbooks/inventory playbooks/nodes/03-install-docker.yaml --ask-become-pass
# Configure Docker to use the specified data root directory for storage.
ansible-playbook -i playbooks/inventory playbooks/nodes/04-setup-docker.yaml --ask-become-pass
```

> For safety, the original Docker data directory at `/var/lib/docker` is neither moved nor deleted. You can manually remove it if you wish to.

## NSight Setup

For [using NSight Systems](https://docs.nvidia.com/nsight-systems/InstallationGuide/index.html#requirements-for-x86-64-and-arm-sbsa-targets-on-linux), it is suggested to set the `perf_event_paranoid` setting to 2. The playbook below will set this setting to 2 until reboot.

```sh
ansible-playbook -i playbooks/inventory playbooks/nodes/05-set-perf-event-paranoid.yaml --ask-become-pass
```

## Team Container Setup

To configure the team containers, you need to complete two files: `data/teams.csv` and `playbooks/inventory`. Run `python compile.py` to generate template versions of these files if they don't exist. The script will pause and prompt you to fill in the required information, and press Enter to continue after each edit. Once the necessary details are provided, the script will generate Docker files and related scripts automatically.

Make sure to distribute teams evenly across the available nodes to optimize GPU utilization. Assigning CPU resources is optional but recommended; you can determine CPU and memory availability using `lscpu` and `free -h`. Also take the NUMA architecture into consideration when assigning CPU/GPU resources. The `IP` column in `data/teams.csv` should be filled with the hostname or IP address specified for each node in the `playbooks/inventory` file.

```sh
rm -rf ./data/dockerfiles/
rm -rf ./data/scripts/
rm -rf ./data/messages/
python compile.py
```

Build the Docker images by running the following command for each team on their corresponding node.

```sh
ansible-playbook -i playbooks/inventory playbooks/containers/01-sync-and-build-docker-images.yaml
```

> If you encountered `429 Too Many Requests` error, login to one of your dedicated Docker Hub personal account on the node with `docker login` and then try again. Full error message:
> ```
> 429 Too Many Requests - Server message: toomanyrequests: You have reached your unauthenticated pull rate limit. https://www.docker.com/increase-rate-limit
> ```

Start all containers on each node by running the following command for each node.

```sh
# Run this initialization script only the first time. For future modifications, use the script mentioned in the next code block.
bash ~/j3soon/scripts/init_node_<NODE_NAME>.sh
```

In case you want to restart the containers, you can run the following command for each container:

```sh
bash ~/j3soon/scripts/docker_run_<CONTAINER_NAME>.sh
# and then press Enter to stop and remove the existing container
```

Check the Docker containers by running the following command for each node.

```sh
ansible-playbook -i playbooks/inventory playbooks/containers/02-check-docker-containers.yaml
```

## Clean up

After the hackathon, you can clean up the cluster environment by reversing the steps above according to the backed up information in the `output` directory.

If there are no containers running on the cluster before set up, you can execute the following commands:

```sh
docker stop $(docker ps -q)
docker rm $(docker ps -aq)
```
