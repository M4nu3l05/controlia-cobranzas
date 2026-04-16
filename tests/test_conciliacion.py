import pandas as pd

from conciliador.conciliacion import build_id


def test_build_id_with_multiple_columns():
    df = pd.DataFrame({"RUT": ["1", "2"], "DV": ["9", "K"]})
    ids = build_id(df, ["RUT", "DV"])
    assert ids.tolist() == ["1_9", "2_K"]
