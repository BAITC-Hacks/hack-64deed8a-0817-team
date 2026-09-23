# Clean-clone judge check — 2026-09-23

Tested commit: `c5339ad` in `/tmp/judge-check` on macOS arm64. This was a
separate clone; the main checkout and its virtual environment were not used
for the judge run.
The system `python3` was **3.13.9** at
`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.
`OPENAI_API_KEY` was absent.

## Commands and results

The user supplied the clean clone after SSH cloning failed with
`Permission denied (publickey)` and HTTPS cloning failed because this machine
had no GitHub credentials. The clone initially had no `.venv` and no tracked
changes. From its root, the README quick-start command
`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
succeeded. The pinned versions **do install on Python 3.13.9**: pandas 3.0.6,
numpy 2.4.6, and pytest 9.1.1, using cached compatible wheels. No extra
package installation, environment file, API key, or code change was needed.

| README command | Result |
| --- | --- |
| `python local_eval.py` | Passed; seed 42 net ARPU **561,775**, 15 pilots, one final campaign. |
| `python local_eval.py --runs 10` | Passed; median **526,464**, minimum **29,194**, maximum **594,076**, **10/10 positive**. |
| `python make_submission.py` | Passed; wrote one final campaign to `submission.csv`. |
| `python -m pytest tests/ -v` | Passed, **20/20**. |
| `python -m pytest tests/test_limits.py -v` | Passed, **5/5**. |

Every distinct runtime and test command shown in the README was run with the
fresh virtual environment active. Commands repeated in multiple README
sections were run once. After `make_submission.py`, the diff against the
committed `submission.csv` was empty; both files had Git
blob hash `be963a4c95c7360bbfdfbaa9f7387e8acb8b37ae`.

## README findings

- The install section says that only Python 3.11 is needed and cites versions
  checked on 3.11. The pinned requirements and all README checks also worked
  on 3.13.9 here, so 3.11 is not an observed requirement. The README does not
  state whether other Python versions are supported.
- The quick-start section still contains `TODO: чистый результат — цифру даст
  капитан после 16:30`. This is an unfinished result placeholder.
- The single-run example reports net ARPU 676,992 and 20 pilots for an older
  `agent.py` v2. Current commit `c5339ad` gives 561,775 and 15 pilots on the
  same seed 42. The example identifies its old version, but a judge looking for
  a current expected output would be misled.
- The robustness table explicitly says it was measured at `98c0980`, but it
  sits in the current README. Its baseline median/minimum (574,550 / 59,765)
  differ from the current ten-seed run (526,464 / 29,194). It needs a clearer
  current-versus-historical label if it is intended as a reproduction target.
- The install block uses `git clone <URL этого репозитория>` rather than a
  concrete URL. It requires the reader to supply the repository address and
  working GitHub access; cloning was the only blocked step on this machine.
- `local_eval.py` printed `Кампаний: 16` while `make_submission.py` wrote one
  campaign. This is consistent with 15 scored pilots plus one final campaign,
  but the README does not explain that the local score's campaign count includes
  pilots. The stated limit of up to 10 applies to final campaigns only.

No README command failed after the clone was supplied. README was not edited.
