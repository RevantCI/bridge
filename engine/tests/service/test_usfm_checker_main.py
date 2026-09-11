from usfm_checker_main import CHECKER_VERSION, main


def test_standalone_checker_has_machine_testable_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"bridge-usfm-checker {CHECKER_VERSION}"
