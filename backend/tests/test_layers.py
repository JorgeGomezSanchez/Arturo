"""Layer catalog contract: every overlay is renderable and explains itself."""

from __future__ import annotations


def test_catalog_has_the_thematic_layers(client):
    layers = {l["id"]: l for l in client.get("/api/layers").json()}
    expected = {
        "mola_hrsc_color_hillshade", "mola_color_hillshade", "mola_hrsc_hillshade",
        "themis_day_ir", "themis_night_ir", "tes_thermal_inertia",
        "tes_albedo", "tes_dust_cover_index", "mola_roughness",
        "tes_high_ca_pyroxene", "tes_plagioclase", "tes_sheet_silicates_glass",
        "geologic_map_sim3292", "valley_networks",
    }
    assert expected <= set(layers)


def test_every_overlay_has_legend_attribution_and_backend_url(client):
    for layer in client.get("/api/layers").json():
        assert layer["tileUrl"].startswith(f"/api/tiles/{layer['id']}/")
        assert layer["attribution"]
        if layer["group"] != "overlay":
            continue
        legend = layer["legend"]
        assert legend and legend["title"] and legend["stops"], layer["id"]
        assert legend["sources"], f"{layer['id']}: legends must cite a source"
        assert isinstance(legend["quantitative"], bool)


def test_ordering_and_special_fields(client):
    layers = client.get("/api/layers").json()
    groups = [l["group"] for l in layers]
    # Base layers first, then overlays, each sorted by zIndex
    assert groups == sorted(groups, key=lambda g: g != "base")
    by_id = {l["id"]: l for l in layers}
    assert by_id["mola_hrsc_hillshade"]["blendMode"] == "multiply"
    assert by_id["themis_day_ir"]["coverage"]["north"] == 65
    assert by_id["geologic_map_sim3292"]["legend"]["type"] == "categorical"
    assert len(by_id["geologic_map_sim3292"]["legend"]["stops"]) > 40
    assert by_id["mola_roughness"]["legend"]["type"] == "channels"
    # Only the base imagery is on at start-up
    assert {l["id"] for l in layers if l["defaultVisible"]} == {"viking_mdim21_color", "ctx_global_5m"}
