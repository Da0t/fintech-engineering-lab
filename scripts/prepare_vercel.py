"""Build a minimal Linux Java runtime and compile the actual engine for Vercel."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def download(url, path):
    with urlopen(Request(url, headers={"User-Agent":"FintechEngineeringLab-build"}), timeout=90) as response, open(path,"wb") as target:
        shutil.copyfileobj(response,target)


def main():
    manifest = json.loads((ROOT/"deployment"/"java.json").read_text())
    with tempfile.TemporaryDirectory(prefix="fintech-jdk-") as directory:
        work=Path(directory)
        archive=work/"jdk.tar.gz"
        print("Downloading the checksum-pinned Java build runtime",flush=True)
        download(manifest["url"],archive)
        digest=hashlib.file_digest(open(archive,"rb"),"sha256").hexdigest()
        if digest != manifest["sha256"]:
            raise RuntimeError("Java archive checksum mismatch")
        with tarfile.open(archive) as tar:
            tar.extractall(work,filter="data")
        jdk=next(path for path in work.iterdir() if path.is_dir() and (path/"bin"/"javac").exists())
        build=ROOT/"marketlab"/"build"
        build.mkdir(parents=True,exist_ok=True)
        subprocess.run([str(jdk/"bin"/"javac"),"-encoding","UTF-8","--release","17","-d",str(build),str(ROOT/"marketlab"/"java"/"MarketEngine.java")],check=True)
        runtime=ROOT/".runtime"/"java"
        if runtime.exists():
            shutil.rmtree(runtime)
        runtime.parent.mkdir(exist_ok=True)
        subprocess.run([str(jdk/"bin"/"jlink"),"--add-modules","java.base","--strip-debug","--no-man-pages","--no-header-files","--compress=2","--output",str(runtime)],check=True)
        smoke=subprocess.run([str(runtime/"bin"/"java"),"-Dfile.encoding=UTF-8","-cp",str(build),"MarketEngine","--batch"],input="STATE\n",text=True,encoding="utf-8",capture_output=True,check=True)
        state=json.loads(smoke.stdout)["state"]
        assert all(state["checks"].values())
        print("Java engine compiled and smoke-tested with the bundled runtime",flush=True)


if __name__=="__main__":
    main()
