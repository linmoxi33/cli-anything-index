import click


@click.group()
def cli():
    pass


@cli.command("draw")
@click.option("--json", "as_json", is_flag=True)
def draw(as_json):
    pass
