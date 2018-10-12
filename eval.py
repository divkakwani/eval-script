#!/usr/bin/python2
"""

General Program Evaluation Script - v0.1

Copyright (C) 2018 Divyanshu Kakwani <divkakwani@gmail.com>

All rights reserved.
"""

from __future__ import print_function

import os
import sys
import subprocess
import argparse
import tempfile
import math
import csv


# Global Logger
logger = None

usage_txt = """
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

# Custom Errors
class ExtractError(Exception):
    pass
class InvalidDirStructError(Exception):
    pass
class MakeFileNotFoundError(Exception):
    pass
class InvalidMakeFileError(Exception):
    pass
class BuildError(Exception):
    pass
class BinaryNotFound(Exception):
    pass


def load_testcases(testdir):
    """
    Loads a list of all the valid testcases obtained from `testdir`
    Each testcase is represented as:
        (num, <input-file-path>, <output-file-path)
    """
    if not os.path.isdir(testdir):
        logger.error("Error loading testcases: Path %s does not exist. Exiting" % testdir)
        sys.exit(-1)
    fnames = set(os.listdir(testdir))
    ip_fmt = 'input-%s.c'
    op_fmt = 'output-%s.txt'
    mx_testcases = 100
    testcases = []
    for num in range(mx_testcases):
        input_file = ip_fmt % num
        output_file = op_fmt % num
        if input_file in fnames and output_file in fnames:
            input_path = os.path.join(testdir, input_file)
            output_path = os.path.join(testdir, output_file)
            testcases.append((num, input_path, output_path))
    return testcases


def extract_tar(tar_path, dir_path):
    """
    Extracts the tar archive into directory referred by dir_path
    Note:
        1. The tar pointed by tar_path must have .tar.gz or .tar.xz extension
    """
    logger.infoH("Extracting your submission")
    logger.info("Creating directory %s to store the submission" % dir_path)
    rc1, output1, error1 = run_cmd('mkdir -p "%s"' % dir_path)
    if rc1 != 0:
        logger.error(error1)
        raise ExtractError()
    logger.info(output1, '\n')
    logger.info("Extracting the tar in the directory")
    rc2, output2, error2 = run_cmd('tar -xvf "%s" -C "%s" --strip 1' % (tar_path, dir_path))
    if rc2 != 0:
        logger.error(error2)
        raise ExtractError()
    logger.info(output2, '\n')


def extract_zip(zip_path, dir_path):
    ret, output, error = run_cmd('unzip "%s" -d "%s"' % (zip_path, dir_path))
    if ret != 0:
        raise ExtractError()
    logger.info(output)


def extract_submissions(zip_path):
    """
    Returns a list of submissions. Each submission is represented as:
        (<submission-name>, <roll-number>, <tar-path>)
    """
    extract_path = tempfile.mkdtemp()
    try:
        extract_zip(zip_path, extract_path)
    except:
        logger.error("Error extracting submissions zip. Exiting")
        sys.exit(-3)
    subdirs = os.listdir(extract_path)
    submissions = []
    for subdir in subdirs:
        name = subdir.split('_')[0]
        tars = os.listdir(os.path.join(extract_path, subdir))
        if len(tars) == 0:
            continue
        tarname = tars[0]
        rollno = tarname.replace('.', '_').split('_')[0].upper()
        submissions.append((name, rollno, os.path.join(extract_path, subdir, tarname)))
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


def collect_args():
    parser = argparse.ArgumentParser(description=usage_txt,
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
    parser.add_argument("-f", "--format", help="Output format. eg csv, json etc")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="Set verbose on/off")
    parser.add_argument("-s", "--summary", action="store_true", default=False, help="Also display statistical summary of all the results")
    args = vars(parser.parse_args())
    if not args['extractdir']:
        args['extractdir'] = tempfile.mkdtemp()
    return args


def build_subm(subm_path):
    cwd = os.getcwd()
    os.chdir(subm_path)
    logger.infoH("Building the submission")
    retcode, output, error = run_cmd("make")
    os.chdir(cwd)
    if retcode != 0:
        logger.error(error)
        raise BuildError()
    logger.info(output, '\n')


class SubmEvaluator:

    def __init__(self, extractdir, testcases):
        self.test_runner = TestRunner(testcases)
        self.extractdir = extractdir

    def evaluate(self, subm):
        """
        Returns evaluation result
        """
        result = {
            "submission": subm,
            "extract_status": None,
            "build_status": None,
            "tc_results": {
                "tests": [],
                "total": 0,
                "passed": 0,
                "failed": 0,
            },
            "score": None,
            "binary_exists": None,
        }
        subm_path = os.path.join(self.extractdir, subm[0])
        try:
            extract_tar(subm[2], subm_path)
            result["extract_status"] = "Passed"
            build_subm(subm_path)
            result["build_status"] = "Passed"
            bin_path = find_binary(subm_path)
            if not bin_path:
                raise BinaryNotFound
            result["binary_exists"] = "Passed"
            result["tc_results"] = self.test_runner.run(bin_path, subm_path)
        except ExtractError:
            result["extract_status"] = "Failed"
        except BuildError:
            result["build_status"] = "Failed"
        except BinaryNotFound:
            result["binary_exists"] = "Failed"
        result["score"] = score_subm(result["tc_results"])
        return result



def score_subm(test_results):
    score = 0
    for (id, status) in test_results["tests"]:
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
        result = {
            "tests": [],
            "total": 0,
            "passed": 0,
            "failed": 0
        }
        asfile_path = os.path.join(subm_path, 'assembly.s')
        exefile_path = os.path.join(subm_path, 'generated.out')
        # Run binary passing the testcase input and store the generated assembly
        cmd1t = '"%s" < "%%s" > "%s"' % (bin_path, asfile_path)
        # Compile the generated assembly into executable
        cmd2 = 'gcc -o "%s" "%s"' % (exefile_path, asfile_path)
        # compare the output of the executable with the testcase output
        cmd3t = '"%s" | diff "%%s" - || :' % (exefile_path)

        logger.infoH("Running Testcases")
        for (num, ipath, opath) in self.testcases:
            result["total"] += 1
            logger.info("Running testcase #", num)
            cmd1 = cmd1t % ipath
            cmd3 = cmd3t % opath
            retcode, output, errormsg = chain_cmd(cmd1, cmd2, cmd3)
            if retcode != 0 or output is None or len(output.strip()) > 0:
                matches = False
            else:
                matches = True
            if matches:
                result["passed"] += 1
                result["tests"].append((num, True))
            else:
                result["failed"] += 1
                result["tests"].append((num, False))
            logger.info("Status: ", ("Passed" if matches else "Failed"))
            if not matches and output is not None:
                logger.info("Diff with the output:")
                logger.info(output)

        return result


class Logger:

    class bcolors:
        HEADER = '\033[95m'
        OKBLUE = '\033[94m'
        OKGREEN = '\033[92m'
        WARNING = '\033[93m'
        FAIL = '\033[91m'
        ENDC = '\033[0m'
        BOLD = '\033[1m'
        UNDERLINE = '\033[4m'

    def __init__(self):
        self.enabled = False

    def enable(self):
        self.enabled = True

    def infoH(self, *args):
        if self.enabled:
            sys.stdout.write(Logger.bcolors.OKBLUE)
            print(*args)
            sys.stdout.write(Logger.bcolors.ENDC)

    def info(self, *args):
        if self.enabled:
            print(*args)

    def error(self, *args):
        sys.stderr.write(Logger.bcolors.FAIL)
        print(*args, file=sys.stderr)
        sys.stderr.write(Logger.bcolors.ENDC)


class Results:

    def __init__(self):
        self.results = []

    def add(self, result):
        self.results.append(result)

    def summarize(self):
        marks = [result["score"] for result in self.results]
        stats = {
            "Mean": (sum(marks) * 1.0) / len(marks),
            "Highest": max(marks),
            "Lowest": min(marks),
        }
        stats["Stddev"] = math.sqrt(sum((x - stats["Mean"])**2 for x in marks))
        for k in stats:
            print("{} = {}".format(k, stats[k]))

    def _error_str(self, result):
        if result["extract_status"] == "Failed":
            return "Error extracting the submission"
        elif result["build_status"] == "Failed":
            return "Error building the submission"
        elif result["binary_exists"] == "Failed":
            return "Error finding a.out"
        else:
            return "-"

    def print(self, format):
        if format == 'csv':
            self.csv()
        else:
            self.tabular()

    def tabular(self):
        print('------------ Evaluation Report --------------------')
        th_pattern = "{0: <30.25}\t{1: <15}\t{2: <15}\t{3: <15}"
        tr_pattern = "{0: <30.25}\t{1: <15}\t{2: <15}\t{3: <15}"
        print(th_pattern.format("Student ID", "Error(s)", "TCs Passed", "Marks"))
        for result in self.results:
            tcs_passed = "{} / {}".format(result["tc_results"]["passed"],
                                          result["tc_results"]["total"])
            print(tr_pattern.format(result["submission"][0],
                                    self._error_str(result),
                                    tcs_passed,
                                    result["score"]))
        print('')

    def _make_comment(self, result):
        err_str = self._error_str(result)
        comment = err_str
        if err_str == '-':
            failed_tcs = ','.join(str(num)
                                  for num, status
                                  in
                                  result["tc_results"]["tests"]
                                  if not status)
            if len(failed_tcs) == 0:
                comment = ""
            else:
                comment = "Failed Testcases: " + failed_tcs
        return comment

    def csv(self):
        header = ["roll_no", "marks", "comments"]
        payload = [[result["submission"][1],
                    result["score"],
                    self._make_comment(result)]
                   for result in self.results]
        csvwriter = csv.writer(sys.stdout)
        csvwriter.writerow(header)
        csvwriter.writerows(payload)


def chain_cmd(*cmds):
    r, o, e = None, None, None
    for cmd in cmds:
        r, o, e = run_cmd(cmd)
        if r != 0:
            return r, o, e
    return r, o, e


def run_cmd(cmdstr):
    """
    Returns:
        (Return Code, contents of stdout, contents of stderr)
    """
    retcode = 0
    output = None
    errormsg = None
    cmd = '/bin/bash -o pipefail -c \'%s\'' % cmdstr
    logger.info("Running command: ", cmdstr)
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as err:
        errormsg = err.output
        retcode = err.returncode

    return (retcode, output, errormsg)


def main():
    global logger
    logger = Logger()
    args = collect_args()
    testcases = load_testcases(args["testdir"])
    if args["verbose"]:
        logger.enable()
    if args["mode"] == "b":
        submissions = extract_submissions(args["src"])
    else:
        name = os.path.basename(args["src"]).split('.')[0]
        submissions = [(name, name, args["src"])]
    evaluator = SubmEvaluator(args["extractdir"], testcases)
    results = Results()
    for subm in submissions:
        logger.infoH("Evaluating submission: %s\n" % subm[0])
        result = evaluator.evaluate(subm)
        results.add(result)
    results.print(args["format"])

    if args["summary"]:
        results.summarize()


if __name__ == '__main__':
    main()
