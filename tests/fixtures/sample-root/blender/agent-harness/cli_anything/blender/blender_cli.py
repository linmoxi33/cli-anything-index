import click


@click.group()
def cli():
    pass


@cli.command("render")
@click.option("--json", "as_json", is_flag=True)
def render(as_json):
    pass


@cli.command()
def scene_add():
    pass
