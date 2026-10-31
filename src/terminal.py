"""Lesing fra terminalen som tåler Ctrl+D og Ctrl+C."""


def les(tekst: str) -> str:
    """Som input(), men Ctrl+D (slutt på input) og Ctrl+C gir «q», slik at programmet avslutter pent."""
    try:
        return input(tekst).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"
