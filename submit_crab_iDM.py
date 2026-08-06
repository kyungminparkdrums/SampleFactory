import json
import subprocess
import re
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--input", required=True, help="JSON file with signal points")
args = parser.parse_args()

with open(args.input) as f:
    config = json.load(f)

chain = config["chain"]
prefix = config["gridpack_prefix"]

for p in config["points"]:

    gridpack = p["gridpack"]
    fragment = p["fragment"]
    nevt     = p["nevents_per_job"]
    njobs    = p["njobs"]

    m = re.search(r"Mchi-[^_]+_dMchi-[^_]+", gridpack)
    mass = m.group(0) if m else "unknown"

    m = re.search(r"ctau-[^_.]+", fragment)
    ctau = m.group(0) if m else "ctau-unknown"

    total = nevt * njobs

    print("\n===========================================")
    print(f"gridpack : {gridpack}")
    print(f"mass     : {mass}")
    print(f"ctau     : {ctau}")
    print(f"events   : {total} ({nevt} x {njobs})")
    print("===========================================\n")

    cmd = [
        "./runFactory.py",
        "-c", f"data/chains/Run2/{chain}",
        "-f", f"data/fragments/{fragment}",
        "-n", str(nevt),
        "-j", str(njobs),
        "--minutes", "2750",
        "--memory", "5000",
        "--nthreads", "4",
        "--crab",
        "--gridpack", gridpack,
        "--gridpack_prefix", prefix
    ]

    print(" ".join(cmd))
    
    #confirm = input("Submit this point? (y/n/q): ")
    #if confirm.lower() == "q":
    #    break
    #if confirm.lower() != "y":
    #    continue

    subprocess.run(cmd, check=True)
