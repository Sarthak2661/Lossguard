import pytest

from scripts.validate_dataset import validate_file


def test_dataset_validation_checks_hash_schema_and_metadata(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text(
        "trans_date_trans_time,cc_num,merchant,category,amt,city_pop,dob,trans_num,lat,long,merch_lat,merch_long,is_fraud\n"
        "2020-01-01 00:00:00,1,m,home,5,10,1990-01-01,t1,1,2,3,4,0\n",
        encoding="utf-8",
    )
    import hashlib

    expected = {
        "rows": 1,
        "min_timestamp": "2020-01-01 00:00:00",
        "max_timestamp": "2020-01-01 00:00:00",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    assert validate_file(path, expected)["rows"] == 1
    with pytest.raises(ValueError, match="SHA-256"):
        validate_file(path, {**expected, "sha256": "0" * 64})
