"""ui.preview_clips (#255): off means no Studio preview loads until its Play is pressed."""
from autostream import cfg, schema
from autostream.ui import studio


def test_default_on_and_in_the_schema():
    assert cfg.DEFAULTS["ui"]["preview_clips"] is True
    assert any(f["path"] == "ui.preview_clips"
               for s in schema.CONFIG_SCHEMA for f in s["fields"])


def test_page_gates_both_preview_grids_on_the_setting():
    src = studio.STUDIO_JS
    assert "studio_previewsOn()" in src
    # style cards and the parts bin both route through the Play placeholder
    assert src.count("studio_lazyPlayBtn(") >= 3
