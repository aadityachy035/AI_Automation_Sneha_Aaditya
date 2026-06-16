import urllib.request
import json
import sys
import os
import zipfile
import subprocess

def install():
    print("Fetching PyPI data for matplotlib...")
    url = "https://pypi.org/pypi/matplotlib/json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
    
    wheel_url = None
    for rel in data['releases']['3.11.0']:
        if 'cp311' in rel['filename'] and 'win_amd64' in rel['filename']:
            wheel_url = rel['url']
            break
            
    if not wheel_url:
        print("Could not find matching wheel for cp311 win_amd64!")
        sys.exit(1)
        
    whl_file = "matplotlib.whl"
    print(f"Downloading {wheel_url}...")
    req = urllib.request.Request(wheel_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response, open(whl_file, 'wb') as out_file:
        out_file.write(response.read())
        
    print("Extracting...")
    site_packages = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "Lib", "site-packages")
    with zipfile.ZipFile(whl_file, 'r') as z:
        z.extractall(site_packages)
        
    os.remove(whl_file)
    print("Done! Verifying...")
    
    python_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "Scripts", "python.exe")
    result = subprocess.run([python_exe, '-c', 'import matplotlib; print("matplotlib OK:", matplotlib.__version__)'], capture_output=True, text=True)
    print(result.stdout.strip())
    print(result.stderr.strip())

if __name__ == "__main__":
    install()
