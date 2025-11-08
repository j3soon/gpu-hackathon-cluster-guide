import csv
import os
import re
import secrets
import shutil
import string
from collections import defaultdict

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def parse_ssh_config(hostname):
    """
    Parse ~/.ssh/config to resolve SSH hostname aliases to actual hostnames/IPs.
    
    Args:
        hostname: The hostname or alias to resolve
    
    Returns:
        The resolved hostname/IP, or the original hostname if not found in SSH config
    """
    # Check if the hostname looks like an IP address (basic check)
    # If it's already an IP, return it as is
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if ip_pattern.match(hostname):
        return hostname
    
    # Try to parse ~/.ssh/config
    ssh_config_path = os.path.expanduser('~/.ssh/config')
    
    if not os.path.exists(ssh_config_path):
        # No SSH config found, return original hostname
        return hostname
    
    try:
        with open(ssh_config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Parse SSH config
        current_host = None
        host_configs = {}
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Check for Host directive
            host_match = re.match(r'^Host\s+(.+)$', line, re.IGNORECASE)
            if host_match:
                current_host = host_match.group(1).strip()
                if current_host not in host_configs:
                    host_configs[current_host] = {}
                continue
            
            # Check for HostName directive
            if current_host:
                hostname_match = re.match(r'^HostName\s+(.+)$', line, re.IGNORECASE)
                if hostname_match:
                    host_configs[current_host]['hostname'] = hostname_match.group(1).strip()
        
        # Try to resolve the hostname
        # First try exact match
        if hostname in host_configs and 'hostname' in host_configs[hostname]:
            return host_configs[hostname]['hostname']
        
    except Exception as e:
        # If any error occurs during parsing, return original hostname
        print(f"⚠️  Warning: Error parsing SSH config for '{hostname}': {e}")
        return hostname
    
    # If hostname not found in SSH config, return original
    return hostname

def read_inventory_vars():
    """
    Read Ansible inventory file and extract variables.
    Returns a dictionary with the extracted variables.
    """
    inventory_path = os.path.join(SCRIPT_DIR, "playbooks", "inventory")
    vars_dict = {}
    
    if not os.path.exists(inventory_path):
        return vars_dict
    
    with open(inventory_path, 'r', encoding='utf-8') as f:
        in_vars_section = False
        for line in f:
            line = line.strip()
            
            # Check if we're entering a vars section
            if line.endswith(':vars]'):
                in_vars_section = True
                continue
            
            # Check if we're leaving the vars section (new section starts)
            if in_vars_section and line.startswith('['):
                in_vars_section = False
                continue
            
            # Parse variable assignments in vars section
            if in_vars_section and '=' in line:
                # Split on first '=' to handle values with '='
                key, value = line.split('=', 1)
                vars_dict[key.strip()] = value.strip()
    
    return vars_dict

def get_workspace_base():
    """
    Get the workspace base path from inventory file.
    Returns the workspace_base path. Exits with error if not found in inventory.
    """
    inventory_vars = read_inventory_vars()
    
    # In the playbook, workspace_base is defined as: {{ data_symlink_path }}/data
    if 'data_symlink_path' not in inventory_vars:
        print("❌ ERROR: 'data_symlink_path' not found in playbooks/inventory [nodes:vars] section.")
        exit(1)
    
    base_path = inventory_vars['data_symlink_path']
    
    # Expand Ansible variables if present (e.g., {{ ansible_env.HOME }})
    if '{{ ansible_env.HOME }}' in base_path:
        base_path = base_path.replace('{{ ansible_env.HOME }}', '$HOME')
    
    return f"{base_path}/data"

def read_csv_data(csv_file):
    """
    Read CSV file and return rows as a list of dictionaries.
    """
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return list(reader)

def write_csv_data(csv_file, rows, fieldnames):
    """
    Write rows back to CSV file.
    Args:
        csv_file: Path to CSV file
        rows: List of dictionaries
        fieldnames: List of column names
    """
    with open(csv_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def check_required_columns(rows):
    """
    Check that all required columns are present in the CSV file.
    Args:
        rows: List of dictionaries from CSV file
    Returns True if all required columns exist, False otherwise.
    """
    required_columns = [
        'Team ID', 'Team Name', 'Cluster', '#GPUs', 'Docker Image',
        'Container Name', 'IP', 'Port', 'GPU IDs', 'Services', 'SSH Password'
    ]

    if not rows:
        print("❌ ERROR: CSV file is empty or has no data rows.")
        return False

    # Get actual columns from the first row
    actual_columns = set(rows[0].keys())
    required_columns_set = set(required_columns)

    # Find missing columns
    missing_columns = required_columns_set - actual_columns

    if missing_columns:
        print("❌ ERROR: Missing required columns in CSV file: " + ", ".join(sorted(missing_columns)))
        return False
    else:
        print("✅ All required columns are present in CSV file.")
        return True

def check_team_mapping(rows):
    """
    Check that team ID and team name has 1-to-1 mapping.
    Args:
        rows: List of dictionaries from CSV file
    """
    # Dictionary to store team_id -> set of team names
    team_id_to_names = defaultdict(set)
    # Dictionary to store team_name -> set of team ids
    team_name_to_ids = defaultdict(set)

    for row in rows:
        team_id = row['Team ID'].strip()
        team_name = row['Team Name'].strip()
        team_id_to_names[team_id].add(team_name)
        team_name_to_ids[team_name].add(team_id)

    # Check for violations
    violations = []

    # Check if any team ID maps to multiple team names
    for team_id, names in team_id_to_names.items():
        if len(names) > 1:
            violations.append(f"⚠️  WARNING: Team ID '{team_id}' maps to multiple team names: {sorted(names)}")

    # Check if any team name maps to multiple team IDs
    for team_name, ids in team_name_to_ids.items():
        if len(ids) > 1:
            violations.append(f"⚠️  WARNING: Team Name '{team_name}' maps to multiple team IDs: {sorted(ids)}")

    # Report results
    if violations:
        print("❌ MAPPING VIOLATIONS FOUND:\n")
        for violation in violations:
            print(violation)
        return False
    else:
        print("✅ All team IDs and team names have 1-to-1 mapping.")
        return True

def check_team_consistency(rows):
    """
    Check team-level consistency:
    - All rows for a team must have identical IP addresses
    - All rows must have identical SSH Passwords
    - All rows for a team must have unique ports
    - All rows for a team must have unique container names
    Args:
        rows: List of dictionaries from CSV file
    Returns True if consistent, False otherwise.
    """
    from collections import defaultdict

    # Group rows by team ID
    teams = defaultdict(list)
    for idx, row in enumerate(rows, start=2):
        team_id = row['Team ID'].strip()
        teams[team_id].append((idx, row))

    violations = []

    for team_id, team_rows in teams.items():
        if len(team_rows) == 1:
            continue  # Single row teams don't need consistency checks

        team_name = team_rows[0][1]['Team Name'].strip()

        # Check 1: All non-empty IPs should be identical
        ips = set()
        for idx, row in team_rows:
            ip = row['IP'].strip()
            if ip:  # Only consider non-empty IP fields
                ips.add(ip)

        if len(ips) > 1:
            violations.append(
                f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}) has multiple different IPs: {', '.join(sorted(ips))}"
            )

        # Check 2: For cluster teams, all non-empty SSH Passwords should be identical
        ssh_passwords = set()
        for idx, row in team_rows:
            ssh_password = row['SSH Password'].strip()
            if ssh_password:  # Only consider non-empty fields
                ssh_passwords.add(ssh_password)

        if len(ssh_passwords) > 1:
            violations.append(
                f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}) with Cluster='Yes' has multiple different SSH Passwords"
            )

        # Check 3: All non-empty ports should be unique
        ports = defaultdict(list)
        for idx, row in team_rows:
            port = row['Port'].strip()
            if port:  # Only consider non-empty ports
                ports[port].append(idx)

        for port, line_numbers in ports.items():
            if len(line_numbers) > 1:
                violations.append(
                    f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}) has duplicate port '{port}' on lines: {', '.join(map(str, line_numbers))}"
                )

        # Check 4: All non-empty container names should be unique
        container_names = defaultdict(list)
        for idx, row in team_rows:
            container_name = row['Container Name'].strip()
            if container_name:  # Only consider non-empty names
                container_names[container_name].append(idx)

        for container_name, line_numbers in container_names.items():
            if len(line_numbers) > 1:
                violations.append(
                    f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}) has duplicate Container Name '{container_name}' on lines: {', '.join(map(str, line_numbers))}"
                )

    # Report results
    if violations:
        print("\n❌ TEAM CONSISTENCY VIOLATIONS FOUND:\n")
        for violation in violations:
            print(violation)
        return False
    else:
        print("✅ All teams have consistent IPs, unique ports, and unique container names.")
        return True

def check_cluster_consistency(rows):
    """
    Check cluster consistency:
    - Non-cluster teams: must have empty Container Name, IP, Port, GPU IDs, Services, and SSH Password
    - Cluster teams: must have non-empty #GPUs, Docker Image, IP, Port, GPU IDs, Services
      - Container Name can be empty or must start with 'team' followed by team ID
      - Services must start with 'ssh'
    Args:
        rows: List of dictionaries from CSV file
    Returns True if consistent, False otherwise.
    """
    violations = []

    for idx, row in enumerate(rows, start=2):  # Start at 2 to account for header
        cluster_value = row['Cluster'].strip().upper()
        team_name = row['Team Name'].strip()
        team_id = row['Team ID'].strip()

        # Check if cluster is some form of "yes"
        is_cluster_yes = cluster_value in ['YES', 'Y']

        if not is_cluster_yes:
            # Non-cluster teams: check that infrastructure fields are empty
            fields_to_check = ['Container Name', 'IP', 'Port', 'GPU IDs', 'Services', 'SSH Password']
            non_empty_fields = []
            for field in fields_to_check:
                value = row[field].strip()
                if value:  # If field is not empty
                    non_empty_fields.append(f"{field}='{value}'")

            if non_empty_fields:
                violations.append(
                    f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}, Line: {idx}) has Cluster='{row['Cluster'].strip()}' "
                    f"but has non-empty fields: {', '.join(non_empty_fields)}"
                )
        else:
            # Cluster teams: check that required fields are non-empty
            required_fields = ['#GPUs', 'Docker Image', 'IP', 'Port', 'GPU IDs', 'Services']
            empty_fields = []
            for field in required_fields:
                value = row[field].strip()
                if not value:  # If field is empty
                    empty_fields.append(field)

            if empty_fields:
                violations.append(
                    f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}, Line: {idx}) has Cluster='Yes' "
                    f"but has empty required fields: {', '.join(empty_fields)}"
                )

            # Check Container Name: can be empty or must start with 'team-XX' (two digit team ID)
            container_name = row['Container Name'].strip()
            if container_name:  # If not empty
                expected_prefix = f"team-{int(team_id):02d}"
                if not container_name.lower().startswith(expected_prefix):
                    violations.append(
                        f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}, Line: {idx}) has Container Name='{container_name}' "
                        f"which should start with '{expected_prefix}'"
                    )

            # Check Services: must start with 'ssh'
            services = row['Services'].strip()
            if services and not services.lower().startswith('ssh'):
                violations.append(
                    f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}, Line: {idx}) has Services='{services}' "
                    f"which should start with 'ssh'"
                )

    # Report results
    if violations:
        print("\n❌ CLUSTER CONSISTENCY VIOLATIONS FOUND:\n")
        for violation in violations:
            print(violation)
        return False
    else:
        print("✅ All teams pass cluster consistency checks.")
        return True

def check_services_validity(rows):
    """
    Check that all services in the Services column are valid.
    Valid services are: 'ssh', 'jupyter-lab'

    Args:
        rows: List of dictionaries from CSV file
    Returns:
        True if all services are valid, False otherwise.
    """
    valid_services = {'ssh', 'jupyter-lab'}
    violations = []

    for idx, row in enumerate(rows, start=2):  # Start at 2 to account for header
        services_str = row['Services'].strip()

        if not services_str:
            continue  # Empty services is OK for non-cluster teams

        team_name = row['Team Name'].strip()
        team_id = row['Team ID'].strip()

        # Split services by comma and trim whitespace
        services_list = [s.strip().lower() for s in services_str.split(',') if s.strip()]

        # Check each service
        invalid_services = [s for s in services_list if s not in valid_services]

        if invalid_services:
            violations.append(
                f"⚠️  WARNING: Team '{team_name}' (ID: {team_id}, Line: {idx}) has invalid services: {', '.join(invalid_services)}. "
                f"Valid services are: {', '.join(sorted(valid_services))}"
            )

    # Report results
    if violations:
        print("\n❌ SERVICE VALIDATION VIOLATIONS FOUND:\n")
        for violation in violations:
            print(violation)
        return False
    else:
        print("✅ All services are valid.")
        return True

def filter_cluster_yes_teams(rows):
    """
    Filter and return only rows where Cluster='Yes'.

    Args:
        rows: List of dictionaries from CSV file
    Returns:
        List of rows where Cluster is 'Yes' or 'Y' (case-insensitive)
    """
    cluster_yes_rows = []
    for row in rows:
        cluster_value = row['Cluster'].strip().upper()
        if cluster_value in ['YES', 'Y']:
            cluster_yes_rows.append(row)
    return cluster_yes_rows

def generate_random_password(length=20):
    """
    Generate a cryptographically secure random password of specified length.
    Uses letters and digits.
    """
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))

def fill_ssh_passwords(rows):
    """
    For each team with Cluster='Yes', if SSH Password is empty for all rows, generate and assign a random password.
    Modifies rows in place.
    Args:
        rows: List of dictionaries from CSV file
    Returns:
        tuple: (rows, passwords_generated_flag)
    """
    # Filter only Cluster='Yes' teams
    cluster_yes_rows = filter_cluster_yes_teams(rows)

    # Group rows by team ID
    teams = defaultdict(list)
    for row in cluster_yes_rows:
        team_id = row['Team ID'].strip()
        teams[team_id].append(row)

    passwords_generated = []

    for team_id, team_rows in teams.items():
        if not team_rows:
            continue

        # Check if all SSH passwords are empty for this team
        all_empty = all(row['SSH Password'].strip() == '' for row in team_rows)

        if all_empty:
            # Generate a random password
            password = generate_random_password(20)
            team_name = team_rows[0]['Team Name'].strip()

            # Assign the password to all rows of this team
            for row in team_rows:
                # Assigning the password directly, modifies the original row as rows are mutable and passed by reference
                row['SSH Password'] = password

            passwords_generated.append((team_id, team_name, password))

    # Report generated passwords
    if passwords_generated:
        print("🔑 Generated SSH passwords for Cluster='Yes' teams with empty passwords:\n")
        for team_id, team_name, password in passwords_generated:
            print(f"  Team '{team_name}' (ID: {team_id}): {password}")
        print()

    return rows, len(passwords_generated) > 0

def create_docker_run_scripts(rows):
    """
    For each team with Cluster='Yes', create a docker run script in data/scripts/ directory.
    Each script contains the docker run command with all necessary arguments.
    If container_name is empty, use 'team-XX' format where XX is the 2-digit team ID.

    Args:
        rows: List of dictionaries from CSV file
    Returns:
        int: Number of scripts created
    """
    # Filter only Cluster='Yes' teams
    cluster_yes_rows = filter_cluster_yes_teams(rows)
    
    # Get workspace base from inventory
    workspace_base_default = get_workspace_base()

    scripts_created = []

    for row in cluster_yes_rows:
        team_id = row['Team ID'].strip()
        team_name = row['Team Name'].strip()
        container_name = row['Container Name'].strip()
        port = row['Port'].strip()
        gpu_ids = row['GPU IDs'].strip()
        cpu_ids = row.get('CPU IDs', '').strip()
        mem_ids = row.get('Mem IDs', '').strip()
        memory = row.get('Memory', '').strip()
        ulimit_stack = row.get('Ulimit Stack', '').strip()

        # Determine the container name to use
        team_prefix = f"team-{int(team_id):02d}"
        if not container_name:
            container_name = team_prefix

        # Default values from the playbook
        default_shm_size = "16GB"
        default_ulimit_memlock = "-1"
        default_ulimit_stack = "67108864"

        # Use custom ulimit_stack if provided, otherwise use default
        stack_value = ulimit_stack if ulimit_stack else default_ulimit_stack

        # Build optional docker flags
        optional_flags = ""
        
        # Add optional CPU pinning
        if cpu_ids:
            optional_flags += f"  --cpuset-cpus {cpu_ids} \\\n"
        
        # Add optional memory node pinning
        if mem_ids:
            optional_flags += f"  --cpuset-mems {mem_ids} \\\n"
        
        # Add optional memory limits
        if memory:
            optional_flags += f"  -m {memory} \\\n"
            optional_flags += f"  --memory-swap {memory} \\\n"
        
        # Add GPU devices
        if gpu_ids:
            optional_flags += f'  --gpus \'"device={gpu_ids}"\' \\\n'

        # Build docker run script
        script_lines = f"""#!/bin/bash

# Docker run script for {team_name} (Team ID: {team_id})
# Container: {container_name}

# Configuration
WORKSPACE_BASE="{workspace_base_default}"

# Create necessary directories
mkdir -p "$WORKSPACE_BASE/{team_prefix}"
mkdir -p "$WORKSPACE_BASE/{team_prefix}_ssh"

echo "Hi {team_prefix}, please store your team's data here." | tee "$WORKSPACE_BASE/{team_prefix}/README.txt" > /dev/null

# Create Docker network if it doesn't exist
docker network inspect {team_prefix}_network >/dev/null 2>&1 || \\
  docker network create {team_prefix}_network

# Stop and remove existing container if it exists, press Enter to confirm
if docker ps -a --format '{{{{.Names}}}}' | grep -wq "{container_name}"; then
  read -p "Container '{container_name}' already exists. Press Enter to stop and remove it, or Ctrl+C to abort..."
  docker stop {container_name} >/dev/null 2>&1 || true
  docker rm {container_name} >/dev/null 2>&1 || true
fi

# Run Docker container
docker run -it -d --name {container_name} \\
  --network {team_prefix}_network \\
  -p {port}:22 \\
  --shm-size={default_shm_size} \\
  --ulimit memlock={default_ulimit_memlock} \\
  --ulimit stack={stack_value} \\
  --cap-add=BPF \\
  --cap-add=PERFMON \\
{optional_flags}  -v "$WORKSPACE_BASE/{team_prefix}:/workspace" \\
  -v "$WORKSPACE_BASE/{team_prefix}_ssh:/root/.ssh" \\
  {container_name}:latest

# Display status
if [ $? -eq 0 ]; then
  echo "✅ Container {container_name} started successfully"
  echo "📡 Access via: ssh root@$(hostname -I | awk '{{print $1}}') -p {port}"
else
  echo "❌ Failed to start container {container_name}"
  exit 1
fi
"""

        # Create script file
        script_filename = f"docker_run_{container_name}.sh"
        script_path = os.path.join(SCRIPT_DIR, "data", "scripts", script_filename)

        # Write the script
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_lines)

        # Make script executable
        os.chmod(script_path, 0o755)

        scripts_created.append((team_name, team_id, container_name, script_filename))

    # Report created scripts
    if scripts_created:
        print("📜 Created Docker run scripts for Cluster='Yes' teams:\n")
        for team_name, team_id, container_name, script_filename in scripts_created:
            print(f"  Team '{team_name}' (ID: {team_id}): {script_filename}")
        print()

    return len(scripts_created)

def create_dockerfiles(rows):
    """
    For each team with Cluster='Yes', create a Dockerfile in data/dockerfiles/ directory.
    Each Dockerfile uses the base image from the 'Docker Image' column.
    If container_name is empty, use 'team-XX' format where XX is the 2-digit team ID.

    Args:
        rows: List of dictionaries from CSV file
    Returns:
        int: Number of Dockerfiles created
    """
    # Read the common fragment (lines 4-19)
    common_fragment_path = os.path.join(SCRIPT_DIR, "dockerfile-fragments", "common", "Dockerfile")
    common_fragment_lines = []
    if os.path.exists(common_fragment_path):
        with open(common_fragment_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            # Get lines 4 to 19 (0-indexed: lines 3 to 18)
            common_fragment_lines = all_lines[3:19]

    # Read the SSH server fragment (lines 3-36)
    ssh_fragment_path = os.path.join(SCRIPT_DIR, "dockerfile-fragments", "openssh-server", "Dockerfile")
    ssh_fragment_lines = []
    if os.path.exists(ssh_fragment_path):
        with open(ssh_fragment_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            # Get lines 3 to 36 (0-indexed: lines 2 to 35)
            ssh_fragment_lines = all_lines[2:36]

    # Read the Jupyter Lab fragment (lines 8-27)
    jupyter_fragment_path = os.path.join(SCRIPT_DIR, "dockerfile-fragments", "jupyter-lab", "Dockerfile")
    jupyter_fragment_lines = []
    if os.path.exists(jupyter_fragment_path):
        with open(jupyter_fragment_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            # Get lines 8 to 27 (0-indexed: lines 7 to 26)
            jupyter_fragment_lines = all_lines[7:27]

    # Filter only Cluster='Yes' teams
    cluster_yes_rows = filter_cluster_yes_teams(rows)

    dockerfiles_created = []

    for row in cluster_yes_rows:
        team_id = row['Team ID'].strip()
        team_name = row['Team Name'].strip()
        docker_image = row['Docker Image'].strip()
        container_name = row['Container Name'].strip()
        services_str = row['Services'].strip()
        ssh_password = row['SSH Password'].strip()

        # Parse services list
        services_list = [s.strip().lower() for s in services_str.split(',') if s.strip()]

        # Determine the container name to use
        team_prefix = f"team-{int(team_id):02d}"
        if not container_name:
            container_name = team_prefix

        # Create Dockerfile path
        dockerfile_path = os.path.join(SCRIPT_DIR, "data", "dockerfiles", team_prefix, f"Dockerfile_{container_name}")

        # Create Dockerfile content
        dockerfile_content = f"FROM {docker_image}\n"

        # Change to root user
        dockerfile_content += "\n"
        dockerfile_content += "# =====Prologue=====\n\n"
        dockerfile_content += "USER root\n"
        dockerfile_content += "SHELL [\"/bin/bash\", \"-c\"]\n"

        # Always add common tools fragment
        dockerfile_content += "\n"
        dockerfile_content += "# =====Common Tools=====\n\n"
        dockerfile_content += "".join(common_fragment_lines)
        dockerfile_content += "\n"

        # If Services contains 'ssh', append the SSH server fragment
        if 'ssh' in services_list:
            dockerfile_content += "# =====OpenSSH Server=====\n\n"
            dockerfile_content += "".join(ssh_fragment_lines)
            dockerfile_content += "\n"

        # If Services contains 'jupyter-lab', append the Jupyter Lab fragment
        if 'jupyter-lab' in services_list:
            dockerfile_content += "# =====Jupyter Lab=====\n\n"
            dockerfile_content += "".join(jupyter_fragment_lines)
            dockerfile_content += "\n"

        # Set the default working directory and clear entrypoint
        dockerfile_content += "# =====Epilogue=====\n\n"
        dockerfile_content += "# Set default directory (mounted later)\n"
        dockerfile_content += 'RUN echo "cd /workspace" >> /root/.bashrc\n'
        dockerfile_content += "\n"
        dockerfile_content += "ENTRYPOINT []\n"

        # Always append the supervisord CMD line
        dockerfile_content += 'CMD ["/usr/bin/supervisord", "-n"]\n'

        # Write the Dockerfile
        os.makedirs(os.path.dirname(dockerfile_path), exist_ok=True)
        with open(dockerfile_path, 'w', encoding='utf-8') as f:
            f.write(dockerfile_content)

        dockerfiles_created.append((team_name, team_id, container_name, docker_image))

    # Report created Dockerfiles
    if dockerfiles_created:
        print("🐳 Created Dockerfiles for Cluster='Yes' teams:\n")
        for team_name, team_id, container_name, docker_image in dockerfiles_created:
            print(f"  Team '{team_name}' (ID: {team_id}): Dockerfile_{container_name} (base: {docker_image})")
        print()

    return len(dockerfiles_created)

def create_init_node_scripts(rows):
    """
    For each unique node (IP), create an init_node_{NAME}.sh script that executes
    all docker_run* commands for that node.
    
    Args:
        rows: List of dictionaries from CSV file
    Returns:
        int: Number of init scripts created
    """
    # Filter only Cluster='Yes' teams
    cluster_yes_rows = filter_cluster_yes_teams(rows)
    
    # Group rows by node (IP)
    nodes = defaultdict(list)
    for row in cluster_yes_rows:
        node_name = row['IP'].strip()
        if node_name:  # Only process rows with valid node names
            nodes[node_name].append(row)
    
    scripts_created = []
    
    for node_name, node_rows in nodes.items():
        # Collect all docker_run scripts for this node
        docker_run_scripts = []
        for row in node_rows:
            team_id = row['Team ID'].strip()
            container_name = row['Container Name'].strip()
            
            # Determine the container name to use
            team_prefix = f"team-{int(team_id):02d}"
            if not container_name:
                container_name = team_prefix
            
            script_filename = f"docker_run_{container_name}.sh"
            docker_run_scripts.append((container_name, script_filename))
        
        # Create the init script content
        script_lines = f"""#!/bin/bash

# Initialization script for node: {node_name}
# This script executes all docker_run commands for containers on this node

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"

echo "======================================"
echo "Initializing node: {node_name}"
echo "======================================"
echo ""

"""
        
        # Add each docker_run script execution
        for idx, (container_name, script_filename) in enumerate(docker_run_scripts, 1):
            script_lines += f"""echo "[{idx}/{len(docker_run_scripts)}] Starting container: {container_name}"
echo "--------------------------------------"
if [ -f "$SCRIPT_DIR/{script_filename}" ]; then
  bash "$SCRIPT_DIR/{script_filename}"
  if [ $? -eq 0 ]; then
    echo "✅ Successfully started {container_name}"
  else
    echo "❌ Failed to start {container_name}"
  fi
else
  echo "❌ Script not found: $SCRIPT_DIR/{script_filename}"
fi
echo ""

"""
        
        # Add final summary
        script_lines += f"""echo "======================================"
echo "Node initialization complete: {node_name}"
echo "======================================"
echo ""
echo "Container status:"
docker ps --filter "name=team-" --format "table {{{{.Names}}}}\\t{{{{.Status}}}}\\t{{{{.Ports}}}}"
"""
        
        # Create script file
        script_filename = f"init_node_{node_name}.sh"
        script_path = os.path.join(SCRIPT_DIR, "data", "scripts", script_filename)
        
        # Write the script
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_lines)
        
        # Make script executable
        os.chmod(script_path, 0o755)
        
        scripts_created.append((node_name, len(docker_run_scripts), script_filename))
    
    # Report created scripts
    if scripts_created:
        print("🚀 Created node initialization scripts:\n")
        for node_name, num_containers, script_filename in scripts_created:
            print(f"  Node '{node_name}': {script_filename} ({num_containers} containers)")
        print()
    
    return len(scripts_created)

def update_inventory_containers(rows):
    """
    Update the [containers] section in the Ansible inventory file with container
    information from CSV data.
    
    Args:
        rows: List of dictionaries from CSV file
    Returns:
        int: Number of containers added to inventory
    """
    # Filter only Cluster='Yes' teams
    cluster_yes_rows = filter_cluster_yes_teams(rows)
    
    # Collect container information
    containers = []
    for row in cluster_yes_rows:
        team_id = row['Team ID'].strip()
        container_name = row['Container Name'].strip()
        node_name = row['IP'].strip()
        port = row['Port'].strip()
        ssh_password = row['SSH Password'].strip()
        
        if not node_name:
            continue  # Skip rows without node names
        
        # Resolve SSH aliases to actual hostnames/IPs
        resolved_node_name = parse_ssh_config(node_name)
        
        # Determine the container name to use
        team_prefix = f"team-{int(team_id):02d}"
        if not container_name:
            container_name = team_prefix
        
        containers.append((container_name, resolved_node_name, port, ssh_password))
    
    # Read the current inventory file
    inventory_path = os.path.join(SCRIPT_DIR, "playbooks", "inventory")
    
    if not os.path.exists(inventory_path):
        print("❌ ERROR: playbooks/inventory file not found")
        return 0
    
    with open(inventory_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the [containers] section
    containers_section_idx = -1
    for idx, line in enumerate(lines):
        if line.strip() == '[containers]':
            containers_section_idx = idx
            break
    
    if containers_section_idx == -1:
        print("❌ ERROR: [containers] section not found in inventory file")
        return 0
    
    # Find where the [containers] section ends (next section or end of file)
    next_section_idx = len(lines)
    for idx in range(containers_section_idx + 1, len(lines)):
        if lines[idx].strip().startswith('[') and lines[idx].strip().endswith(']'):
            next_section_idx = idx
            break
    
    # Build the new [containers] section
    new_container_lines = []
    for container_name, node_name, port, ssh_password in containers:
        new_container_lines.append(
            f"{container_name} ansible_host={node_name} ansible_user=root ansible_password={ssh_password} "
            f"ansible_port={port} ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'\n"
        )
    
    # Reconstruct the inventory file
    new_lines = (
        lines[:containers_section_idx + 1] +  # Everything up to and including [containers]
        new_container_lines +                  # New container entries
        lines[next_section_idx:]               # Everything from next section onwards
    )
    
    # Write back to inventory file
    with open(inventory_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    # Report results
    if containers:
        print("📋 Updated inventory [containers] section:\n")
        for container_name, node_name, port, ssh_password in containers:
            print(f"  {container_name} (on {node_name}:{port})")
        print()
    
    return len(containers)

def create_team_messages(rows):
    """
    For each team with Cluster='Yes', create a message file in data/messages/ directory.
    Each message contains the SSH credentials for the team to access their containers.
    
    Args:
        rows: List of dictionaries from CSV file
    Returns:
        int: Number of message files created
    """
    # Filter only Cluster='Yes' teams
    cluster_yes_rows = filter_cluster_yes_teams(rows)
    
    # Group rows by team ID
    teams = defaultdict(list)
    for row in cluster_yes_rows:
        team_id = row['Team ID'].strip()
        teams[team_id].append(row)
    
    messages_created = []
    
    for team_id, team_rows in teams.items():
        if not team_rows:
            continue
        
        team_name = team_rows[0]['Team Name'].strip()
        
        # Build message content
        message_lines = f"""# SSH Credentials for {team_name} (Team ID: {team_id})

Document link: <https://github.com/j3soon/gpu-hackathon-cluster-guide/blob/main/README.md>

Note: **ALWAYS** store your team's data in the `/workspace` directory.

"""
        
        # Add credentials for each container
        for idx, row in enumerate(team_rows, 1):
            container_name = row['Container Name'].strip()
            ip_address = row['IP'].strip()
            port = row['Port'].strip()
            ssh_password = row['SSH Password'].strip()
            
            # Resolve SSH aliases to actual hostnames/IPs
            resolved_ip_address = parse_ssh_config(ip_address)
            
            # Determine the container name to use
            team_prefix = f"team-{int(team_id):02d}"
            if not container_name:
                container_name = team_prefix
            
            if len(team_rows) > 1:
                message_lines += f"## Container {idx}: `{container_name}`\n\n"
            
            message_lines += f"""```
| Name           | Value                    |
|----------------|--------------------------|
| SSH IP Address | {resolved_ip_address:<24} |
| SSH Port       | {port:<24} |
| SSH Password   | {ssh_password:<24} |
```

SSH Command:

```
ssh root@{resolved_ip_address} -p {port} -L 8888:localhost:8888 -L 6006:localhost:6006
```

and optionally open Jupyter Lab (http://localhost:8888) to check if you can access it.
"""
            
            if idx < len(team_rows):
                message_lines += "\n"
        
        # Create message file
        message_filename = f"team-{int(team_id):02d}_credentials.txt"
        message_path = os.path.join(SCRIPT_DIR, "data", "messages", message_filename)
        
        # Write the message
        os.makedirs(os.path.dirname(message_path), exist_ok=True)
        with open(message_path, 'w', encoding='utf-8') as f:
            f.write(message_lines)
        
        messages_created.append((team_name, team_id, message_filename, len(team_rows)))
    
    # Report created messages
    if messages_created:
        print("💬 Created message files for Cluster='Yes' teams:\n")
        for team_name, team_id, message_filename, num_containers in messages_created:
            print(f"  Team '{team_name}' (ID: {team_id}): {message_filename} ({num_containers} container(s))")
        print()
    
    return len(messages_created)

if __name__ == "__main__":
    csv_file = os.path.join(SCRIPT_DIR, "data", "teams.csv")
    template_file = os.path.join(SCRIPT_DIR, "data", "teams_template.csv")

    # Check if teams.csv exists, if not copy from template
    if not os.path.exists(csv_file):
        if os.path.exists(template_file):
            print(f"⚠️  teams.csv not found. Copying from teams_template.csv...")
            shutil.copy2(template_file, csv_file)
            print(f"✅ Created teams.csv from template.\n")
            print(f"📝 Please edit {csv_file} with your team information.")
            input("Press Enter to continue after editing the file...")
            print()
        else:
            print(f"❌ ERROR: Neither teams.csv nor teams_template.csv found in data/ directory.")
            exit(1)

    # Check if inventory exists, if not copy from inventory_template
    inventory_file = os.path.join(SCRIPT_DIR, "playbooks", "inventory")
    inventory_template_file = os.path.join(SCRIPT_DIR, "playbooks", "inventory_template")

    if not os.path.exists(inventory_file):
        if os.path.exists(inventory_template_file):
            print(f"⚠️  inventory file not found. Copying from inventory_template...")
            shutil.copy2(inventory_template_file, inventory_file)
            print(f"✅ Created inventory from template.\n")
            print(f"📝 Please edit {inventory_file} with your node information.")
            input("Press Enter to continue after editing the file...")
            print()
        else:
            print(f"❌ ERROR: Neither inventory nor inventory_template found in playbooks/ directory.")
            exit(1)

    # Read CSV file
    rows = read_csv_data(csv_file)

    # Get fieldnames from the first row
    if rows:
        fieldnames = list(rows[0].keys())
    else:
        print("❌ ERROR: CSV file is empty")
        exit(1)

    # Run validation checks
    if not check_required_columns(rows):
        exit(1)
    if not check_team_mapping(rows):
        exit(1)
    if not check_team_consistency(rows):
        exit(1)
    if not check_cluster_consistency(rows):
        exit(1)
    if not check_services_validity(rows):
        exit(1)

    # Fill in missing SSH passwords
    rows, passwords_updated = fill_ssh_passwords(rows)

    # Write back to CSV if passwords were generated
    if passwords_updated:
        write_csv_data(csv_file, rows, fieldnames)
        print("✅ Updated CSV file with generated SSH passwords\n")

    # Create Dockerfiles for all teams with Cluster='Yes'
    dockerfiles_count = create_dockerfiles(rows)
    if dockerfiles_count > 0:
        print(f"✅ Created {dockerfiles_count} Dockerfile(s)\n")

    # Create Docker run scripts for all teams with Cluster='Yes'
    scripts_count = create_docker_run_scripts(rows)
    if scripts_count > 0:
        print(f"✅ Created {scripts_count} Docker run script(s)\n")
    
    # Create node initialization scripts
    init_scripts_count = create_init_node_scripts(rows)
    if init_scripts_count > 0:
        print(f"✅ Created {init_scripts_count} node initialization script(s)\n")
    
    # Update inventory [containers] section
    containers_count = update_inventory_containers(rows)
    if containers_count > 0:
        print(f"✅ Updated inventory with {containers_count} container(s)\n")
    
    # Create team message files
    messages_count = create_team_messages(rows)
    if messages_count > 0:
        print(f"✅ Created {messages_count} team message file(s)\n")
