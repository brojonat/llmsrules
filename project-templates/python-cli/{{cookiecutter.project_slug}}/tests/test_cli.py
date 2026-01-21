from click.testing import CliRunner

from {{cookiecutter.package_name}}.cli import cli


def test_hello():
    runner = CliRunner()
    result = runner.invoke(cli, ["hello", "--name", "Test"])
    assert result.exit_code == 0
    assert "Hello, Test!" in result.output


def test_foo_do_something():
    runner = CliRunner()
    result = runner.invoke(cli, ["foo", "do-something"])
    assert result.exit_code == 0
    assert "Foo: Done!" in result.output


def test_bar_greet():
    runner = CliRunner()
    result = runner.invoke(cli, ["bar", "greet", "World", "--count", "2"])
    assert result.exit_code == 0
    assert result.output.count("Hello, World!") == 2
