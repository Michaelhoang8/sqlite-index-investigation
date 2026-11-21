"""Keep report tables keyboard-scrollable without changing table contents."""


def responsive(document: str) -> str:
    css = """
<style id="responsive-tables">
.table-scroll{max-width:100%;width:100%;overflow-x:auto}
.table-scroll:focus-visible{outline:2px solid currentColor;outline-offset:4px}
.grid>*,.triple>*,.plan-pair>*,.panel{min-width:0}
</style>
"""
    if 'id="responsive-tables"' in document:
        raise ValueError("Responsive report styling is already present")
    document = document.replace("</style>", "</style>" + css, 1)
    number = 0
    pieces = document.split("<table")
    for index in range(1, len(pieces)):
        number += 1
        pieces[index] = (f'<div class="table-scroll" role="region" tabindex="0" '
                         f'aria-label="Data table {number}; scroll horizontally to see all columns"><table' + pieces[index])
    return "".join(pieces).replace("</table>", "</table></div>")
