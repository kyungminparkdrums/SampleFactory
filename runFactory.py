#!/usr/bin/env python3
from datetime import datetime

import json
import configparser
import os, sys
import argparse
import warnings

from scripts.logger import Logger
from scripts.argparser import ArgParser

import re
import importlib.util

class SubmitFactory:
    def __init__(self):
        self.WARNINGS = 0
        self.TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.FACTORY = os.getenv("FACTORY")
        self.MY_NAME = os.getenv("USER")

        self.BASE_OS = []

        self.ARGS = vars(ArgParser(__file__))
        self.ARGS["memory"] = str(self.ARGS["memory"])
        self.ARGS["minutes"] = str(self.ARGS["minutes"])
        
        self.__validate_ARGS()

        self.__prepare_JOBS()
        self.__submit_JOBS()

    def __read_JSON(self, json_file):
        out = None
        with open(json_file) as rf:
            out = json.load(rf)
        if not out:
            Logger.ERROR(json_file + " is empty")
        return out

    def __parse_year(self):
        name = self.CHAIN_NAME

        if "UL18" in name:
            return "2018"
        elif "UL17" in name:
            return "2017"
        elif "UL16" in name and "APV" in name:
            return "2016APV"
        elif "UL16" in name and "APV" not in name:
            return "2016"

    def __parse_mass(self):
        m = re.search(r"Mchi-[^_]+_dMchi-[^_]+", self.GRIDPACK)
        if not m:
            raise RuntimeError(f"Could not parse mass from gridpack: {gridpack}")
        return m.group(0)

    def __parse_ctau(self):
        base = os.path.basename(self.ARGS["fragment"])
        m = re.search(r"ctau-[^_.]+", base)
        if not m:
            raise RuntimeError(f"Could not parse ctau from fragment name: {base}")
        return m.group(0)

    """
    def __parse_ctau(self):
        base = os.path.basename(self.ARGS["fragment"])
        m = re.search(r"ctau-(\d+(?:p\d+)?)", base)
        if not m:
            raise RuntimeError(f"Could not parse ctau from fragment name: {base}")

        raw = m.group(1)          # e.g. "1", "10", "0p1"
 
        return raw   
    """

    def __extract_gridpack_info(self, fragment_path):
        spec = importlib.util.spec_from_file_location("fragment", fragment_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        prefix = getattr(module, "gridpackPath_prefix", "")
        name = getattr(module, "gridpackPath", None)

        return prefix, name

    def __validate_ARGS(self):
        if not os.path.exists(self.ARGS["chain"]):
            Logger.ERROR(self.ARGS["chain"] + " does not exist")
        if os.getenv("ProcId"):
            self.PROCID = os.getenv("ProcId")
        else:
            self.PROCID = "0"

    def __validate_JOBS(self, steps, workflows, keeps):
        if set(steps) != set(workflows.keys()) or len(set(steps)) != len(steps):
            # print (steps)
            # print (workflows.keys())
            # Logger.WARNING("STEPS : " + steps)
            # Logger.WARNING("WORKFLOWS : " + workflows.keys())
            Logger.ERROR("Defined STEPS and WORKFLOWS does not agree")
        for k in keeps:
            if not (k in steps):
                # Logger.WARNING("STEPS : " + steps)
                # Logger.WARNING("KEEPS : " + keeps)
                Logger.WARNING("Defined STEPS and KEEPS do not agree")

    def __prepare_JOBS(self):
        chain_json = self.__read_JSON(self.ARGS["chain"])
        
        self.GRIDPACK = self.ARGS.get("gridpack")
        self.GRIDPACK_PREFIX = self.ARGS.get("gridpack_prefix", "")

        self.NEVENTS = self.ARGS.get("nevents")

        if not self.GRIDPACK:
            Logger.ERROR("gridpack argument is required")

        steps = chain_json["STEPS"]
        workflows = chain_json["WORKFLOWS"]
        keeps = chain_json["KEEPS"]
        self.keeps = keeps
        self.files = chain_json.get("FILES",[])

        user_json = self.__read_JSON(f"configs/user_{self.MY_NAME}.json")
        self.XROOTD_HOST = user_json.get("XROOTD_HOST", None)
        self.LFN_PATH = user_json.get("LFN_PATH", None)
        self.CRAB_PATH = user_json.get("CRAB_PATH", None)
        self.CRAB_SITE = user_json.get("CRAB_SITE", None)
        self.AccountingGroup = user_json.get("AccountingGroup", None)

        self.__validate_JOBS(steps=steps, workflows=workflows, keeps=keeps)
        if self.ARGS["fragment"]:
            if os.path.exists(self.ARGS["fragment"]):
                self.FRAGMENT_NAME = os.path.basename(self.ARGS["fragment"]).split(".")[0]
            else: 
                Logger.ERROR("Fragment not found")
        else:
            if self.ARGS["memory"]:
                self.FRAGMENT_NAME = self.ARGS["name"]
            else:
                self.FRAGMENT_NAME = "job" 

        self.CHAIN_NAME = os.path.basename(self.ARGS["chain"]).split(".")[0]

        self.MASS = self.__parse_mass()
        self.CTAU = self.__parse_ctau()
        self.YEAR = self.__parse_year()

        self.LABEL = f"{self.YEAR}_{self.MASS}_{self.CTAU}"

        #self.JOBDIR = f"{self.FRAGMENT_NAME}/{self.CHAIN_NAME}/{self.TIMESTAMP}"
        self.JOBDIR = f"{self.FRAGMENT_NAME}/{self.LABEL}/{self.TIMESTAMP}"
        self.SUBMITDIR = f"{os.environ['PWD']}/jobs/{self.JOBDIR}"

        os.system(f"mkdir -p {self.SUBMITDIR}")
        for file in self.files:
            os.system(f"cp {file} {self.SUBMITDIR}")

        run_writes = []
        run_writes.append(f"#!/usr/bin/env bash\n")
        run_writes.append(f"cat /etc/os-release\n")
        if self.ARGS["crab"] and all([git_cfg in user_json for git_cfg in ["git_name", "git_mail", "git_username"]]):
            run_writes.append(f'git config --global user.name \'{user_json["git_name"]}\'')
            run_writes.append(f'git config --global user.email \'{user_json["git_mail"]}\'')
            run_writes.append(f'git config --global user.github {user_json["git_username"]}')

        if user_json.get("envs", False):
            if not isinstance(user_json["envs"], dict):
                raise TypeError("envs in user json must be a dict")
            for k,v in user_json["envs"].items():
                run_writes.append(f"export {k}='{v}'")    
                run_writes.append(f"export GRIDPACK='{self.GRIDPACK}'")
                run_writes.append(f"export NEVENTS='{self.NEVENTS}'")
 
        run_writes.append("echo 'JOBINDEX ===>' ${PROCID}\n")
        run_writes.append(f"source /cvmfs/cms.cern.ch/cmsset_default.sh\n")
        # steps that requires fragments as inputs (root requests)
        req_frags = ["wmLHEGS", "wmLHE", "GS", "wmLHEGEN", "GEN"]
        for wf_idx, (wf, cfg) in enumerate(workflows.items()):
            cmsdriver_writes = []
            run_writes.append(f"####################################")
            run_writes.append(f"echo 'STEP {wf_idx} : {wf}'")

            CMSSW_VERSION = cfg.get("CMSSW_VERSION",None)
            SCRAM_ARCH = cfg.get("SCRAM_ARCH", None)
            OPTIONS = cfg.get("OPTIONS", None)
            CUSTOMIZES = cfg.get("CUSTOMIZES",None)  # TODO

            # append OS for unit test apptainers for now
            # TODO not sure what to do with this for now
            # do we have any campaigns that runs on different OS releases?
            self.BASE_OS.append(SCRAM_ARCH)

            if SCRAM_ARCH:
                run_writes.append(f"export SCRAM_ARCH={SCRAM_ARCH}")
            if CMSSW_VERSION:
                run_writes.append(f"cmsrel {CMSSW_VERSION}")
                run_writes.append(f"cd {CMSSW_VERSION}/src")
                run_writes.append(f"cmsenv")
                run_writes.extend(CUSTOMIZES.get("cmssw", []))
                if CUSTOMIZES.get("cmssw", []):
                    run_writes.append(f"scram b -j 4") 
                run_writes.append(f"cd ../..\n")

            give_fragment = any(req_frag in wf for req_frag in req_frags)
            run_writes.extend(CUSTOMIZES.get("pre-cmsRun", [])) 
            previous_wf = list(workflows.keys())[wf_idx - 1]
            if OPTIONS:
                if give_fragment:
                    fragment_path = os.path.join("Configuration", "GenProduction", "python")
                    run_writes.append(f"mkdir -p {CMSSW_VERSION}/src/{fragment_path}/")
                    run_writes.append(f"cp fragment.py {CMSSW_VERSION}/src/{fragment_path}/")
                    run_writes.append(f"cd {CMSSW_VERSION}/src")
                    run_writes.append(f"scram b")
                    run_writes.append(f"cd ../..\n")
                    cmsdriver_writes.append(f"{fragment_path}/fragment.py")

                    cmsdriver_writes.append(f"-n " + self.ARGS["nevents"])
                    if self.ARGS["nout"]:
                        cmsdriver_writes.append(f" -o " + self.ARGS["nout"])
                    if self.ARGS["nthreads"]:
                        cmsdriver_writes.append(f" --nThreads " + self.ARGS["nthreads"])
                                        
                    cmsdriver_writes.append(
                        f' --customise_commands "from IOMC.RandomEngine.RandomServiceHelper import RandomNumberServiceHelper; randSvc = RandomNumberServiceHelper(process.RandomNumberGeneratorService); randSvc.populate();'
                    )
                    if self.ARGS["crab"]:
                        jobId="int(os.environ.get('CRAB_Id',1))"
                    else:
                        jobId="int(os.environ.get('PROCID',1))"
                    cmsdriver_writes.append(
                        f'import os; process.source.firstLuminosityBlock = cms.untracked.uint32(10000+{jobId});"'
                    )
                    previous_wf = None
                else:
                    cmsdriver_writes.append(f"{wf}")
                    cmsdriver_writes.append(f"-n -1")
                    cmsdriver_writes.append(f"--filein file:{previous_wf}.root")
                cmsdriver_writes.append(f"--fileout file:{wf}.root")
                cmsdriver_writes.append(f"--python_filename {wf}.py")
                cmsdriver_writes.append(f"--no_exec")
                for opt_name, opt_value in OPTIONS.items():
                    if opt_name == "pileup_input":
                        continue
                    if opt_value is None:
                        cmsdriver_writes.append(f"--{opt_name}")
                    else:
                        cmsdriver_writes.append(f"--{opt_name} {opt_value}")
                if "pileup_input" in OPTIONS.keys():
                    if self.ARGS["das_premix"]:
                        cmsdriver_writes.append(f"--pileup_input {OPTIONS['pileup_input']}")
                    else:
                        cmsdriver_writes.append(f"--pileup_input filelist:pileup.txt")
                        if os.path.exists(f"{self.FACTORY}/data/pileups/{self.CHAIN_NAME}.txt"):
                            os.system(f"cp {self.FACTORY}/data/pileups/{self.CHAIN_NAME}.txt {self.SUBMITDIR}/pileup.txt")
                        elif os.path.exists(f"{os.environ['PWD']}/data/pileups/{self.CHAIN_NAME}.txt"):
                            os.system(f"cp {os.environ['PWD']}/data/pileups/{self.CHAIN_NAME}.txt {self.SUBMITDIR}/pileup.txt")
                        else:
                            Logger.ERROR(f"could not find {self.FACTORY}/data/pileups/{self.CHAIN_NAME}.txt")

                    # ignore log for premix step as it prints out all pileup_input
                    cmsdriver_writes.append("&> /dev/null")

                os.system(f"touch {self.SUBMITDIR}/pileup.txt")  # FIXME stupid hacky line to make NanoGEN work without thinking

                cmsdriver_cmd = "cmsDriver.py"
                for cmsdriver_write in cmsdriver_writes:
                    cmsdriver_cmd += f" {cmsdriver_write}"

                run_writes.append(cmsdriver_cmd)
                run_writes.append(f"time cmsRun {wf}.py")
                if "pileup_input" in OPTIONS.keys():
                    run_writes.append(f"for ATTEMPT in {{1..10}}; do")
                    run_writes.append(f"    if [ -f \"{wf}.root\" ]; then")
                    run_writes.append(f"        if ! edmFileUtil -f \"{wf}.root\" &>/dev/null; then")
                    run_writes.append(f"            echo SAMPLEFACTORY::{wf}.root is corrupted")
                    run_writes.append(f"        else")
                    run_writes.append(f"            NEVENTS=$(edmFileUtil -f \"{wf}.root\" | grep -oP '\\(\\d+ runs, \\d+ lumis, \\K\\d+(?= events)')")
                    run_writes.append(f"            if [[ -z \"$NEVENTS\" ]]; then")
                    run_writes.append(f"                echo SAMPLEFACTORY::Could not parse number of events in {wf}.root")
                    run_writes.append(f"            elif (( NEVENTS == 0 )); then")
                    run_writes.append(f"                echo SAMPLEFACTORY::{wf}.root has 0 events, likely corrupted")
                    run_writes.append(f"            else")
                    run_writes.append(f"                echo SAMPLEFACTORY::Finished processing {wf}.root with trials $ATTEMPT")
                    run_writes.append(f"                break")
                    run_writes.append(f"            fi")
                    run_writes.append(f"        fi")
                    run_writes.append(f"    fi")
                    run_writes.append(f"    echo SAMPLEFACTORY::Could not find valid {wf}.root, resubmitting with trials $ATTEMPT")
                    run_writes.append(f"    time cmsRun {wf}.py")
                    run_writes.append(f"done")

            run_writes.extend(CUSTOMIZES.get("post-cmsRun", [])) 
            if previous_wf not in keeps and previous_wf is not None and (wf_idx+1) != len(workflows) and not CUSTOMIZES.get("keep_input", False):
                run_writes.append(f"rm {previous_wf}.root")
            if not CUSTOMIZES.get("keep", True) and (wf_idx+1) != len(workflows):
                run_writes.append(f"rm -rf {CMSSW_VERSION}")

            #Check if output file exists
            run_writes.append(
                (
                f'\nif [ ! -f "{wf}.root" ]; then\n'
                f'    echo "Error: File {wf}.root not found."\n'
                 '    exit 1\n'
                 'fi\n'
                )
            )

            #Check if output file has >0 events
            run_writes.append(
                (
                f'ENTRIES=$(root -l -b -q -e \'TFile* f = TFile::Open("{wf}.root"); TTree* t = (TTree*)f->Get("Events"); if(t) printf(\"%lld\", t->GetEntries()); f->Close();\' | tail -n 1)\n'
                 'if [[ ! "$ENTRIES" =~ ^[0-9]+$ ]] || [ "$ENTRIES" -eq 0 ]; then\n'
                f'    echo "Error: {wf}.root is an invalid or empty ROOT file (Entries: $ENTRIES)."\n'
                 '    exit 1\n'
                 'fi\n'
                )
            )   
            run_writes.append(f"####################################\n")

        run_writes.append(f"####################################")
        
        if not self.ARGS["crab"]:
            os.system(f"xrdfs {self.XROOTD_HOST} mkdir -p {self.LFN_PATH}/SampleFactory/{self.JOBDIR}")
            for keep in keeps:
                xrdcp_file = f"{keep}_" + "${PROCID}.root"
                run_writes.append(f"echo '{keep}.root will be xrdcped as' {xrdcp_file}")
                run_writes.append(f"xrdfs {self.XROOTD_HOST} mkdir -p {self.LFN_PATH}/SampleFactory/{self.JOBDIR}")
                run_writes.append(f"xrdcp {keep}.root {self.XROOTD_HOST}/{self.LFN_PATH}/SampleFactory/{self.JOBDIR}/{xrdcp_file}")
            run_writes.append("rm *.root")

        with open(f"{self.SUBMITDIR}/run.sh", "w") as wf:
            for run_write in run_writes:
                wf.write(run_write + "\n")
        os.system(f"chmod a+x {self.SUBMITDIR}/run.sh")

        if self.ARGS["fragment"]:
            os.system(f"cp " + self.ARGS["fragment"] + f" {self.SUBMITDIR}/fragment.py")

            # Gridpack handling
            full_path = self.GRIDPACK_PREFIX + self.GRIDPACK if self.GRIDPACK_PREFIX else self.GRIDPACK
            local_path = f"{self.SUBMITDIR}/{self.GRIDPACK}"

            print(f"[SubmitFactory] Staging gridpack:")
            print(f"  remote: {full_path}")
            print(f"  local : {local_path}")

            if not os.path.exists(local_path):
                os.system(f"xrdcp {full_path} {local_path}")

            if not os.path.exists(local_path):
                Logger.ERROR(f"Failed to stage gridpack: {full_path}")

            self.files.append(self.GRIDPACK)

    def __submit_JOBS(self):
        launching_os = self.BASE_OS[0].split("_")[0]
        if launching_os.endswith("7"):
            os_version = "el7"
        elif launching_os.endswith("8"):
            os_version = "el8"
        elif launching_os.endswith("9"):
            os_version = "el9"

        Logger.INFO("################################")
        Logger.INFO("################################")
        Logger.INFO(f"JOBDIR : jobs/{self.JOBDIR}")
        Logger.INFO(f"XROOTD_HOST : {self.XROOTD_HOST}")
        Logger.INFO(f"LFN_PATH : {self.LFN_PATH}/{self.JOBDIR}")
        # Logger.INFO(f"JOBID : {self.PROCID}")
        Logger.INFO("################################")
        for arg_name, arg_value in self.ARGS.items():
            Logger.INFO(f"{arg_name} : {arg_value}")
        Logger.INFO("################################")
        Logger.INFO("################################")

        os.system(f"cp $(voms-proxy-info --path) {self.SUBMITDIR}/MyProxy")
        files = [f"{self.SUBMITDIR}/{f}" for f in self.files]
        files.append(f"{self.SUBMITDIR}/pileup.txt")
        if self.ARGS["fragment"]:
            files.append(f"{self.SUBMITDIR}/fragment.py")
        if not self.ARGS["crab"]:
            assert self.ARGS["flavor"] in ["espresso", "microcentury", "longlunch",
                                           "workday", "tomorrow", "testmatch", "nextweek"],f"""
            {self.ARGS['flavor']} is not a valid flavor.

            espresso     = 20 minutes
            microcentury = 1 hour
            longlunch    = 2 hours
            workday      = 8 hours
            tomorrow     = 1 day
            testmatch    = 3 days
            nextweek     = 1 week
            """

            os.system(f"cp {self.FACTORY}/data/condor/" + self.ARGS["host"] + f"/condor.jds {self.SUBMITDIR}/")
            #os.system(f"sed -i 's|@@JobBatchName@@|{self.FRAGMENT_NAME}__{self.CHAIN_NAME}|g' {self.SUBMITDIR}/condor.jds")

            request_name = f"iDMe_{self.LABEL}"
            os.system(f"sed -i 's|@@JobBatchName@@|{request_name}|g' {self.SUBMITDIR}/crab.py")            
            os.system(f"sed -i 's|@@RequestMemory@@|" + self.ARGS["memory"] + f"|g' {self.SUBMITDIR}/condor.jds")
            # TODO generalize needed inputs for other use cases
            files = ",".join(files)
            os.system(f"sed -i 's|@@transfer_input_files@@|{files}|g' {self.SUBMITDIR}/condor.jds")
            os.system(f"sed -i 's|@@SUBMITDIR@@|{self.SUBMITDIR}|g' {self.SUBMITDIR}/condor.jds")
            os.system(f"sed -i 's|@@MyWantOS@@|{os_version}|g' {self.SUBMITDIR}/condor.jds")
            os.system(f"sed -i 's|@@queue@@|" + self.ARGS["njobs"] + f"|g' {self.SUBMITDIR}/condor.jds")
            os.system(f"sed -i 's|@@flavor@@|" + self.ARGS["flavor"] + f"|g' {self.SUBMITDIR}/condor.jds")            


            if self.AccountingGroup:
                os.system(f"sed -i 's|@@AccountingGroup@@|+AccountingGroup = \"{self.AccountingGroup}\"|g' {self.SUBMITDIR}/condor.jds")
            else:
                os.system(f"sed -i '/@@AccountingGroup@@/d' {self.SUBMITDIR}/condor.jds")
                

            os.chdir(self.SUBMITDIR)
            if self.ARGS["test"]:
                Logger.INFO(f"Testing the submission script in {self.SUBMITDIR}")
                os.system(f"cmssw-{os_version} -- $(echo {self.SUBMITDIR}/run.sh) > test.log.{self.TIMESTAMP}")
                with open(f"test.log.{self.TIMESTAMP}") as rf:
                    if "Traceback" in rf.read():
                        Logger.ERROR(f"Traceback error found in the log file test.log.{self.TIMESTAMP}")
            else:
                os.system(f"condor_submit {self.SUBMITDIR}/condor.jds")
            os.chdir(self.FACTORY)

            print("\n------------------- SUBMIT SETTINGS -------------------\n")
            os.system(f"cat {self.SUBMITDIR}/condor.jds")

            print("\n----------------------- RUN.SH ------------------------\n")
            os.system(f"cat {self.SUBMITDIR}/run.sh")

            #if not self.ARGS["skip_confirm"]:
            #    confirmation = input("Do you want to submit? (y/n) ")
            #    if confirmation.lower()!="y":
            #        os.system(f"rm -rf {self.SUBMITDIR}")
            #        return

        else:
            os.system(f"cp {self.FACTORY}/data/crab/crab.py {self.SUBMITDIR}/")
            os.system(f"sed -i 's|@@JobBatchName@@|{self.FRAGMENT_NAME}__{self.CHAIN_NAME}|g' {self.SUBMITDIR}/crab.py")
            os.system(f"sed -i 's|@@RequestMemory@@|" + self.ARGS["memory"] + f"|g' {self.SUBMITDIR}/crab.py")
            os.system(f"sed -i 's|@@minutes@@|" + self.ARGS["minutes"] + f"|g' {self.SUBMITDIR}/crab.py")

            files = [f.split(self.SUBMITDIR)[-1].rsplit("/", 1)[-1] for f in files]
            files = [self.SUBMITDIR+f"/{f}" for f in files]
            files = '"' +  '","'.join(files) +'"'

            os.system(f"sed -i 's|@@transfer_input_files@@|{files}|g' {self.SUBMITDIR}/crab.py")
            os.system(f"sed -i 's|@@SUBMITDIR@@|{self.SUBMITDIR}|g' {self.SUBMITDIR}/crab.py")
            os.system(f"sed -i 's|@@njobs@@|" + self.ARGS["njobs"] + f"|g' {self.SUBMITDIR}/crab.py")
            os.system(f"sed -i 's|@@nevents@@|" + self.ARGS["nevents"] + f"|g' {self.SUBMITDIR}/crab.py")
            #os.system(f"sed -i 's|@@OUTDIR@@|{self.CRAB_PATH}/SampleFactory|g' {self.SUBMITDIR}/crab.py")
            outdir = f"{self.CRAB_PATH}/{self.YEAR}/MINIAOD/{self.MASS}/{self.CTAU}"
            os.system(f"sed -i 's|@@OUTDIR@@|{outdir}|g' {self.SUBMITDIR}/crab.py")

            request_name = f"iDMe_{self.LABEL}"
            os.system(f"sed -i 's|@@LABEL@@|{self.LABEL}|g' {self.SUBMITDIR}/crab.py")
            os.system(f"sed -i 's|@@TIMESTAMP@@|{self.TIMESTAMP}|g' {self.SUBMITDIR}/crab.py")
 
            os.system(f"sed -i 's|@@SITE@@|{self.CRAB_SITE}|g' {self.SUBMITDIR}/crab.py")
            if self.ARGS["blacklist"]:
                os.system(f"sed -i 's|@@BLACKLIST@@|" + self.ARGS["blacklist"].replace(',','","') + f"|g' {self.SUBMITDIR}/crab.py")
            else:
                os.system(f"sed -i '/@@BLACKLIST@@/d' {self.SUBMITDIR}/crab.py")

            if self.ARGS["whitelist"]:
                os.system(f"sed -i 's|@@WHITELIST@@|" + self.ARGS["whitelist"].replace(',','","') + f"|g' {self.SUBMITDIR}/crab.py")
            else:
                os.system(f"sed -i '/@@WHITELIST@@/d' {self.SUBMITDIR}/crab.py")

            outfiles = '","'.join([f'{k}.root' for k in self.keeps[:-1]])
            if outfiles:
                os.system(f"sed -i 's|@@output_files@@|{outfiles}|g' {self.SUBMITDIR}/crab.py")
            else:
                os.system(f"sed -i '/@@output_files@@/d' {self.SUBMITDIR}/crab.py")

            #run.sh
            os.system(f"sed -i 's|cmsrel|scramv1 project|g' {self.SUBMITDIR}/run.sh")
            os.system(f"sed -i 's|cmsenv|eval `scramv1 runtime -sh`|g' {self.SUBMITDIR}/run.sh")
            os.system(f"sed -i 's|cmsRun|cmsRun -j FrameworkJobReport.xml -- |g' {self.SUBMITDIR}/run.sh")

            os.system(f"cp {self.FACTORY}/data/crab/PSet.py {self.SUBMITDIR}/")
            os.system(f"sed -i 's|@@output@@|{self.keeps[-1]}|g' {self.SUBMITDIR}/PSet.py")

            #crab_submit
            os.system(f"cp {self.FACTORY}/data/crab/crab_submit.sh {self.SUBMITDIR}/")
            if self.ARGS["test"]:
                Logger.INFO(f"Testing the submission script in {self.SUBMITDIR} (dryrun)")
                os.system(f"sed -i 's|crab submit -c crab.py|crab submit -c crab.py --dryrun|g' {self.SUBMITDIR}/crab_submit.sh")

            print("\n================ Double-check this ================")
            print(f"CHAIN      : {self.CHAIN_NAME}")
            print(f"GRIDPACK   : {self.GRIDPACK}")
            print(f"PREFIX     : {self.GRIDPACK_PREFIX}")
            print(f"MASS       : {self.MASS}")
            print(f"CTAU       : {self.CTAU}")
            print(f"YEAR       : {self.YEAR}")
            print(f"OUTDIR     : {outdir}")
            print("=============================================\n")

            #input("Press Enter to submit!")

            print("\n------------------- SUBMIT SETTINGS -------------------\n")
            os.system(f"cat {self.SUBMITDIR}/crab.py")

            print("\n----------------------- RUN.SH ------------------------\n")
            os.system(f"cat {self.SUBMITDIR}/run.sh")

            #if not self.ARGS["skip_confirm"]:
            #    confirmation = input("Do you want to submit? (y/n) ")
            #    if confirmation.lower()!="y":
            #        os.system(f"rm -rf {self.SUBMITDIR}")
            #        return
            os.system(f"cd {self.SUBMITDIR}; ./crab_submit.sh")
                
if __name__ == "__main__":
    SubmitFactory()

