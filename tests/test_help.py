"""omaudit help: command list and per-command how-to."""
from omaudit.cli import EXIT_OK, EXIT_USAGE, main
from omaudit.helptext import PAGES, overview, page, topics


def test_bare_invocation_prints_overview(capsys):
    assert main([]) == EXIT_OK
    out = capsys.readouterr().out
    assert "omaudit add <git-url>" in out
    assert "omaudit help <command>" in out


def test_help_with_no_topic_matches_overview(capsys):
    assert main(["help"]) == EXIT_OK
    assert capsys.readouterr().out == overview()


def test_help_dash_h_matches_overview(capsys):
    assert main(["--help"]) == EXIT_OK
    assert "Everyday" in capsys.readouterr().out


def test_help_add_has_flags_and_example(capsys):
    assert main(["help", "add"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "omaudit add <git-url>" in out
    assert "--local" in out
    assert "Install anyway?" in out


def test_help_check_covers_builtin_and_all(capsys):
    assert main(["help", "check"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "--builtin" in out
    assert "--all" in out
    assert "[a]ccept" in out


def test_help_grades(capsys):
    assert main(["help", "grades"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "A  clean" in out
    assert "Composition pairs" in out


def test_help_unknown_topic_is_usage(capsys):
    assert main(["help", "nope"]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "no help for 'nope'" in err
    assert "add" in err


def test_subcommand_help_is_not_the_overview(capsys):
    assert main(["check", "--help"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "--builtin" in out
    assert "[a]ccept" in out
    assert "Everyday" not in out


def test_unknown_command_points_at_help(capsys):
    assert main(["explode"]) == EXIT_USAGE
    assert "unknown command" in capsys.readouterr().err


def test_every_command_has_a_help_page():
    for name in topics():
        text = page(name)
        assert text, name
        assert name in text or PAGES[name]["summary"] in text
        assert PAGES[name]["usage"]
        assert PAGES[name]["body"].strip()
