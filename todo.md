
* Make it adaptible for every kind of assignment. Parameterize:
    * Execution of a single testcase on the submission
        * Account for generated files, like assembly files
        * Allow output validation strategies other than just diffing the outputs
    * Loading testcases
    * Scoring strategy
* Introduce --dump-csv option
* Show comments instead of error in the evaluation report
* Create better abstraction over command execution
* Improve usage text -- show examples
* Classify all kinds of error and show them in the evaluation report
* Document code
* Improve verbose output
