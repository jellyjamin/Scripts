import subprocess
import os
import shutil
from datetime import datetime
import ftplib
import pyzipper

##################################################
#               helper functions                 #
##################################################

def Await_run(command, input_text=None):
    """Run command, optionally passing input_text to stdin"""
    process = subprocess.Popen(
        command, shell=True, executable="/bin/bash",
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = process.communicate(
        input=input_text.encode() if input_text else None
    )
    if process.returncode != 0:
        print(f"[!] Error running: {command}")
        print(stderr.decode())
    return stdout.decode(), stderr.decode()


def latest_file_in_dir(path, prefix=""):
    files = [os.path.join(path, f) for f in os.listdir(path) if f.startswith(prefix)]
    if not files:
        return None
    return max(files, key=os.path.getctime)


def zip_with_password(src_dir, dest_zip, password):
    """Create a password-protected zip using AES encryption."""
    with pyzipper.AESZipFile(dest_zip, 'w', compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password.encode())
        for root, _, files in os.walk(src_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, start=src_dir)
                zf.write(file_path, arcname)


##################################################
#               BACKUP CONFIG                    #
##################################################

BACKUP_CONFIG = {
    "immich": {
        "enabled": True, # false if not using immich
        "backup_dir": "/your/folder/Pictures/backups",
        "other_dirs": [
            "/your/folder/Pictures/library",
            "/your/folder/Pictures/profile",
            "/your/folder/Pictures/upload",
        ],
        "docker_pg_cmd": (
            'docker exec -t immich_postgres pg_dumpall '
            '--clean --if-exists --username=postgres | gzip > "{file}"'
        )
    },

    "directories": [
        "/lets/back-up/MUSIC",
        "/your/backup/folder/goes/here"
    ]
}

TEMP_ZIP_DIR = "your/temp/zipping/folder/temp-zip-folder"

# master password for all encrypted ZIPs
MASTER_PASSWORD = "Place-password-here"  # set this

# global FTPS settings
FTPS_SERVER = "Change_me"
FTPS_USER = "Change_me"
FTPS_PASS = "Change_me"  # set your FTPS password
FTPS_REMOTE_DIR = "/your-remote-backup-vps-folder"
FTPS_PORT = 21  # change if needed


##################################################
#               1. backup creation               #
##################################################

def backup_immich():
    print("[*] Backing up Immich")
    cfg = BACKUP_CONFIG["immich"]
    os.makedirs(TEMP_ZIP_DIR, exist_ok=True)

    # Step 1: trigger DB dump first
    dump_file = os.path.join(cfg["backup_dir"], "dump.sql.gz")
    print(f"[*] Creating Immich database dump at {dump_file}")
    Await_run(cfg["docker_pg_cmd"].format(file=dump_file))

    # Step 2: grab the most recent immich-db-backup
    latest_db_backup = latest_file_in_dir(cfg["backup_dir"], "immich-db-backup")
    files_to_include = [f for f in [latest_db_backup, dump_file] if f]

    # Step 3: stage files
    staging = os.path.join(TEMP_ZIP_DIR, "immich_staging")
    os.makedirs(staging, exist_ok=True)

    for f in files_to_include:
        print(f"[*] Adding DB file {f}")
        shutil.copy(f, staging)

    # Step 4: copy other Immich directories
    for d in cfg["other_dirs"]:
        name = os.path.basename(d.rstrip("/"))
        print(f"[*] Adding Immich directory {d}")
        shutil.copytree(d, os.path.join(staging, name), dirs_exist_ok=True)

    # Step 5: zip them all with master password
    immich_zip = os.path.join(
        TEMP_ZIP_DIR,
        f"immich-backup-{datetime.now().strftime('%Y%m%dT%H%M%S')}.zip"
    )
    zip_with_password(staging, immich_zip, MASTER_PASSWORD)
    shutil.rmtree(staging)

    print(f"[+] Immich backup created: {immich_zip}")
    return immich_zip


def backup_other_dirs():
    """Zip other directories individually with master password"""
    created = []
    os.makedirs(TEMP_ZIP_DIR, exist_ok=True)
    for d in BACKUP_CONFIG["directories"]:
        zip_name = os.path.join(
            TEMP_ZIP_DIR,
            os.path.basename(d.rstrip("/")) + "-" +
            datetime.now().strftime("%Y%m%dT%H%M%S") + ".zip"
        )
        zip_with_password(d, zip_name, MASTER_PASSWORD)
        created.append(zip_name)
    return created


##################################################
#        2. FTPS upload + versioning             #
##################################################

def upload_with_versioning(zip_files):
    ftp = ftplib.FTP_TLS()
    ftp.connect(FTPS_SERVER, FTPS_PORT)
    ftp.login(FTPS_USER, FTPS_PASS)
    ftp.prot_p()

    # ensure remote dir exists
    try:
        ftp.cwd(FTPS_REMOTE_DIR)
    except ftplib.error_perm:
        print(f"[*] Remote dir {FTPS_REMOTE_DIR} not found, creating...")
        ftp.mkd(FTPS_REMOTE_DIR)
        ftp.cwd(FTPS_REMOTE_DIR)

    for local_file in zip_files:
        base = os.path.basename(local_file)
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        remote_name = f"{base}.{timestamp}"

        # check existing remote files
        matching = [f for f in ftp.nlst() if f.startswith(base)]
        matching.sort()
        upload = True
        if matching:
            last_file = matching[-1]
            ftp.voidcmd("TYPE I")
            size_remote = ftp.size(last_file)
            size_local = os.path.getsize(local_file)
            if size_remote == size_local:
                upload = False
                print(f"[-] Skipping {base}, same size as last remote")

        if upload:
            with open(local_file, "rb") as f:
                ftp.storbinary(f"STOR {remote_name}", f)
            print(f"[+] Uploaded {remote_name}")

        # Retention: keep newest 3 versions only
        matching = [f for f in ftp.nlst() if f.startswith(base)]
        matching.sort()
        while len(matching) > 3:
            ftp.delete(matching[0])
            matching.pop(0)

    ftp.quit()


##################################################
#               3. cleanup                       #
##################################################

def cleanup():
    for folder in [TEMP_ZIP_DIR]:
        for f in os.listdir(folder):
            path = os.path.join(folder, f)
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)


##################################################
#               main pipeline                    #
##################################################

def main():
    all_zips = []

    if BACKUP_CONFIG["immich"]["enabled"]:
        all_zips.append(backup_immich())

    all_zips.extend(backup_other_dirs())

    print("[+] Created encrypted ZIPs:")
    for z in all_zips:
        print("   -", z)

    upload_with_versioning(all_zips)

    cleanup()
    print("[✓] Backup pipeline complete.")


if __name__ == "__main__":
    main()
