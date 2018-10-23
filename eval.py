#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# General Program Evaluation Script
#
# Copyright © Divyanshu Kakwani 2018, all rights reserved.
#
#

from __future__ import print_function
from pprint import pprint

import os
import sys
import subprocess
import argparse
import tempfile
import math
import csv
import copy
import re


# --- Config varibles ----

verbose = True
gcc_flags = []
gpp_flags = ['-std=c++14']


# commands disabled during the execution of a submission
disabled_cmds = ["g++"]


# --- Global objects and constants ----
cmdex = None

ROLLNO_REGEX = re.compile(r"CS\d{2}B\d{3}", re.IGNORECASE)

USAGE_TXT = """
Description
--------------
eval.py -- Evaluates user submission(s)

Usecases
----------
1. For batch evaluation
    ./eval.py --src <path of zip downloaded from Moodle>
              --testdir <path of dir containing testcases>
              --mode b
              --summary
2. For evaluation of a specific submission
    ./eval.py --src <path of submission tar>
              --testdir <path of dir containing testcases>
              --mode s

"""


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'



### --- Print utility functions ----

def print_error(*args):
    sys.stderr.write(bcolors.FAIL)
    print(*args, file=sys.stderr)
    sys.stderr.write(bcolors.ENDC)


def print_info_header(*args):
    if verbose:
        sys.stdout.write(bcolors.OKBLUE)
        print('')
        print(*args)
        sys.stdout.write(bcolors.ENDC)


def print_info(*args):
    if verbose:
        print(*args)


# ---- Custom Exceptions -----

class IVTarName(Exception):
    """Raised when a submission tar is incorrectly named"""
class ExtractError(Exception):
    """Raised when there is a problem extracting the submission tar"""
class IVDirStruct(Exception):
    """Raised when the submission does not have the right structure"""
class MakeError(Exception):
    """Raised when an error is encountered while running make on a submission"""
class BinaryNotFound(Exception):
    """Raised when no executable got generated after running the make command"""
class TestRunError(Exception):
    """Raised when an error is encountered while running a test"""


def load_testcases(testdir):
    """
    Loads all the testcases contained in `testdir`

    Assumed Directory Structure
    -----------------------------
    testdir:
        testid/
            name.<any-extension>
            ...
        ...
    Tests Representation
    ---------------------
    [
        {
            "id": <test-id>
            <name>: <file-full-path>
            for every name in testid/
        }
    ]
    """
    if not os.path.isdir(testdir):
        message = ("Error loading testcases: Path {} does " + \
                   "not exist. Exiting").format(testdir)
        print_error(message)
        sys.exit(-1)

    testids = set(os.listdir(testdir))
    testids = sorted(testids)
    testcases = []
    for id in testids:
        fnames = os.listdir(os.path.join(testdir, id))
        testcase = {}
        testcase['id'] = id
        for fname in fnames:
            if fname != 'id':
                key = os.path.splitext(fname)[0]
                testcase[key] = os.path.join(testdir, id, fname)
        testcases.append(testcase)

    return testcases


def extract_tar(tar_path, dir_path):
    """
    Extracts the tar archive into directory referred by dir_path.
    The tar pointed by tar_path must have .tar.gz or .tar.xz extension
    """
    print_info("Creating directory %s to store the submission" % dir_path)
    ret, output, error = cmdex.run('mkdir -p "%s"' % dir_path)
    if ret != 0:
        print_error(error)
        raise ExtractError(error)
    print_info("Extracting the tar in the directory")
    ret, output, error = cmdex.run('tar -xvf "%s" -C "%s" --strip 1' % (tar_path, dir_path))
    if ret != 0:
        print_error(error)
        raise ExtractError(error)


def extract_zip(zip_path, dir_path):
    ret, output, error = cmdex.run('unzip "%s" -d "%s"' % (zip_path, dir_path))
    if ret != 0:
        raise ExtractError()


def extract_submissions(zip_path):
    """
    Returns a list of submissions. Each submission is represented as a dict
    with the following keys:
        1. "rollno": roll no. in lower-case. It is picked from the tar name
        2. "tar_path": full path where the submission tar is kept on the system

    Every submission tar is expected to be named as: <rollno>.tar.gz
    """
    extract_path = tempfile.mkdtemp()
    try:
        extract_zip(zip_path, extract_path)
    except Exception as e:
        print_error("Error extracting submissions' zip. Exiting")
        sys.exit(-3)
    subdirs = os.listdir(extract_path)
    submissions = []
    for subdir in subdirs:
        tars = os.listdir(os.path.join(extract_path, subdir))
        if len(tars) == 0:
            continue
        tarname = tars[0]
        match = ROLLNO_REGEX.search(tarname)
        if not match:
            continue    # todo: report that the tar name is invalid
        rollno = match.group().lower()
        submissions.append({
            "rollno": rollno,
            "tarpath": os.path.join(extract_path, subdir, tarname)
        })
    return submissions


def find_binary(dir_path):
    files = os.listdir(dir_path)
    if "a.out" in files:
        return os.path.join(dir_path, "a.out")
    else:
        for file in files:
            fpath = os.path.join(dir_path, file)
            if os.path.isfile(fpath) and os.access(fpath, os.X_OK):
                return fpath
    raise BinaryNotFound


def build_subm(subm_path):
    cwd = os.getcwd()
    os.chdir(subm_path)
    print_info("Cleaning any existing build")
    retcode, output, error = cmdex.run("make clean")
    print_info("Running make")
    retcode, output, error = cmdex.run("make")
    os.chdir(cwd)
    if retcode != 0:
        print_error(error)
        raise MakeError()


class Evaluator:

    def __init__(self, extractdir, testcases):
        self.test_runner = TestRunner(testcases)
        self.extractdir = extractdir

    def evaluate(self, subm):
        """
        Evaluates a submission
        """
        result = {
            "subm_id": subm["rollno"],
            "error_obj": None,
            "nb_tests": None,
            "passed": None,
            "failed": None,
            "tsumm": [],
            "score": None,
        }
        subm_path = os.path.join(self.extractdir, subm["rollno"])
        try:
            print_info_header("Extracting submission...")
            extract_tar(subm["tarpath"], subm_path)
            print_info_header("Building submission...")
            build_subm(subm_path)
            bin_path = find_binary(subm_path)
            print_info_header("Running Testcases")
            tsumm = self.test_runner.run(bin_path, subm_path)
            result["nb_tests"] = len(tsumm)
            result["failed"] = len([1 for _, status in tsumm if not status])
            result["passed"] = result["nb_tests"] - result["failed"]
            result["tsumm"] = tsumm
            result["score"] = score_subm(result["tsumm"])
        except Exception as e:
            result["error_obj"] = e
        return result


def score_subm(tsumm):
    score = 0
    for (id, status) in tsumm:
        if status:
            score += 0.5
    return score


class TestRunner:

    def __init__(self, testcases):
        self.testcases = testcases

    def run(self, bin_path, subm_path):
        """
        @param bin_path Full path of binary
        @param subm_path Full path of the submission directory. This directory
                         is also where the generated files are stored.
        """
        tsumm = []
        asfile_path = os.path.join(subm_path, 'assembly.s')
        exefile_path = os.path.join(subm_path, 'generated.out')
        # Run binary passing the testcase input and store the generated assembly
        cmd1t = '"%s" < "%%s" > "%s"' % (bin_path, asfile_path)
        # Compile the generated assembly into executable
        cmd2 = 'gcc -o "%s" "%s"' % (exefile_path, asfile_path)
        # compare the output of the executable with the testcase output
        cmd3t = '"%s" | diff "%%s" - || :' % (exefile_path)

        for test in self.testcases:
            print_info("\nRunning testcase #", test["id"])
            cmd1 = cmd1t % test["input"]
            cmd3 = cmd3t % test["output"]
            retcode, output, errormsg = cmdex.run(cmd1, cmd2, cmd3)
            if retcode != 0 or output is None or len(output.strip()) > 0:
                matches = False
            else:
                matches = True
            tsumm.append((test["id"], matches))
            print_info("Status: ", ("Passed" if matches else "Failed"))
            if not matches and output is not None:
                print_info("Diff with the output:")
                print_info(output)

        return tsumm


### ------- Functions to print/dump results -----


def make_comment(result):
    errobj = result['error_obj']
    if errobj is not None:
        if isinstance(errobj, IVTarName):
            return 'Invalid Tar Name'
        elif isinstance(errobj, ExtractError):
            return 'Error extracting the submission'
        elif isinstance(errobj, IVDirStruct):
            return 'Invalid directory structure'
        elif isinstance(errobj, MakeError):
            return 'Error encountered while running make'
        elif isinstance(errobj, BinaryNotFound):
            return 'Couldn\'t find executable'
        elif isinstance(errobj, TestRunError):
            return 'Error running test cases'
    if result['nb_tests'] > result['passed']:
        return 'Failed Testcases: ' + \
                ', '.join(id for id, status in result['tsumm']
                          if not status)
    return ''


def dump_csv(results, filename=None):
    fp = open(filename or sys.stdout, "w+") if filename else sys.stdout
    header = ["roll_no", "marks", "comments"]
    payload = [[result['subm_id'],
                result["score"],
                make_comment(result)]
               for result in results]
    csvwriter = csv.writer(fp)
    csvwriter.writerow(header)
    csvwriter.writerows(payload)
    if filename:
        fp.close()


def print_results(results, filename=None):
    fp = open(filename or sys.stdout, "w+") if filename else sys.stdout
    fp.write('\n\nEvaluation Report: \n')
    fp.write('===================================== \n')
    th_pattern = "{0: <15}\t{1: <15}\t{2: <15}\t{3: <15}\n"
    tr_pattern = "{0: <15}\t{1: <15}\t{2: <15}\t{3: <15}\n"
    fp.write(th_pattern.format("Roll No.", "TCs Passed",
                               "Score", "Comment"))
    for result in results:
        tcs_passed = "{} / {}".format(result["passed"], result["nb_tests"])
        fp.write(tr_pattern.format(result["subm_id"], tcs_passed,
                                   result["score"], make_comment(result)))
    if filename:
        fp.close()


def print_summary(results, filename=None):
    fp = open(filename or sys.stdout, "w+") if filename else sys.stdout
    scores = [result["score"] for result in results]
    stats = {
        "Mean": (sum(scores) * 1.0) / len(scores),
        "Highest": max(scores),
        "Lowest": min(scores),
    }
    stats["Stddev"] = math.sqrt(sum((x - stats["Mean"])**2 for x in scores))
    fp.write('\n\nEvaluation Statistics: \n')
    fp.write('===================================== \n')
    for k in stats:
        fp.write("{} = {}\n".format(k, stats[k]))
    if filename:
        fp.close()



class CommandExecutor:
    """
    Interface to run system commands
    """
    def __init__(self):
        self.gcc_fn = 'gcc() { /usr/bin/gcc ' + ' '.join(gcc_flags) + ' "$@"; };'
        self.gpp_fn = 'g++() { /usr/bin/g++ ' + ' '.join(gpp_flags) + ' "$@"; };'
        self.disabled_cmds = ' '.join('%s(){ :; }; ' % cmd
                                      for cmd in disabled_cmds)

    def _run_bash(self, cmd, disable=False):
        # print_info(cmd)
        ret, out, errstr = 0, None, None
        prefix = self.gcc_fn + self.gpp_fn + \
                    (self.disabled_cmds if disable else '')
        ## FIXME: disable cmds will not work
        cmd = '/bin/bash -o pipefail -c \'{} {}\''.format(prefix, cmd)
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                          shell=True)
        except subprocess.CalledProcessError as err:
            errstr = err.output
            ret = err.returncode
        return (ret, out, errstr)

    def run(self, *cmds, **options):
        disable_cmds = options.get('disable_cmds', False)
        ret, out, err = None, None, None
        for cmd in cmds:
            ret, out, err = self._run_bash(cmd, disable_cmds)
            if ret != 0:
                return ret, out, err
        return ret, out, err


def collect_args():
    parser = argparse.ArgumentParser(description=USAGE_TXT,
                                     formatter_class=argparse.RawTextHelpFormatter)
    req_named_args = parser.add_argument_group("required named arguments")
    req_named_args.add_argument("--src", required=True,
                                help="Path of the submission tar")
    req_named_args.add_argument("--testdir", required=True,
                                help="Path of the directory that contains the test case files")
    req_named_args.add_argument("--mode", required=True,
                                help="Batch or single mode. Use 'b' for batch and 's' for single")
    parser.add_argument("--penalty", help="Penalize submission for incorrect format, late submission etc")
    parser.add_argument("--extractdir", help="Directory where the source code will be extracted to")
    parser.add_argument("--dump-csv", help="Dump a csv of the result")
    parser.add_argument("-v", "--verbose", action="store_true",
                        default=False, help="Set verbose on/off")
    parser.add_argument("-s", "--summary", action="store_true", default=False,
                        help="Also display statistical summary of all the results")
    args = vars(parser.parse_args())
    if not args['extractdir']:
        args['extractdir'] = tempfile.mkdtemp()

    if args['verbose']:
        global verbose
        verbose = True

    return args


def init():
    global cmdex
    cmdex = CommandExecutor()


def main():
    init()
    args = collect_args()
    testcases = load_testcases(args["testdir"])
    if args["mode"] == "b":
        submissions = extract_submissions(args["src"])
    else:
        match = ROLLNO_REGEX.search(os.path.basename(args["src"]))
        if not match or not os.path.exists(args["src"]):
            print_error("Invalid tar name or the tar does not exist")
            sys.exit(-5)
        rollno = match.group().lower()
        submissions = [{"rollno": rollno, "tarpath": args["src"]}]
    evaluator = Evaluator(args["extractdir"], testcases)
    results = []
    for subm in submissions:
        print_info_header("Evaluating submission: %s" % subm["rollno"])
        result = evaluator.evaluate(subm)
        results.append(result)

    print_results(results)

    if args["dump_csv"]:
        dump_csv(results, args["dump_csv"])

    if args["summary"]:
        print_summary(results)


if __name__ == '__main__':
    main()
