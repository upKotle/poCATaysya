"""Import exact OSM road ways from downloaded API XML, never POI coordinates.

Run with backend/.venv/bin/python scripts/import_osm_segments.py file1.osm ...
Re-import resets verification to draft. Review changes before replacing reviewed data.
"""
import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString
from shapely.ops import transform

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--selection', type=Path, default=ROOT / 'scripts/initial_segments.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/moscow/scenic_segments.geojson')
    args = parser.parse_args()
    ways, nodes = {}, {}
    for file in args.files:
        root = ET.parse(file).getroot()
        nodes.update({n.attrib['id']: (float(n.attrib['lon']), float(n.attrib['lat'])) for n in root.findall('node')})
        ways.update({w.attrib['id']: w for w in root.findall('way')})
    project = Transformer.from_crs(4326, 32637, always_xy=True).transform
    inverse = Transformer.from_crs(32637, 4326, always_xy=True).transform
    features = []
    for entry in json.loads(args.selection.read_text()):
        way = ways[str(entry['osm_way_id'])]
        tags = {t.attrib['k']: t.attrib['v'] for t in way.findall('tag')}
        if tags.get('highway') not in {'primary', 'secondary', 'tertiary', 'residential', 'unclassified'}:
            raise ValueError('Expected a car road, not a footway/POI')
        if any(tags.get(key) in {'no', 'private'} for key in ('access', 'motor_vehicle', 'motorcar')):
            raise ValueError('Road has an access restriction')
        coords = [nodes[n.attrib['ref']] for n in way.findall('nd')]
        if tags.get('oneway') == '-1':
            coords.reverse()
        line = transform(project, LineString(coords))
        anchors = [inverse(*line.interpolate(line.length * f).coords[0]) for f in (0.02, 0.5, 0.98)]
        features.append({'type':'Feature', 'geometry':{'type':'LineString','coordinates':coords}, 'properties':{
            'id':f"osm-way-{entry['osm_way_id']}", 'name': tags['name'] + ' — участок',
            'routing_anchors':anchors, 'direction':'forward' if tags.get('oneway') in {'yes','1','true','-1'} else 'both',
            **{key:entry[key] for key in ('water','architecture','greenery')},
            'description':'Редакционная гипотеза для поездки. Видимость, качество впечатлений и текущая доступность из автомобиля не проверены.',
            'source_url':f"https://www.openstreetmap.org/way/{entry['osm_way_id']}",
            'osm_way_version':int(way.attrib['version']), 'osm_way_timestamp':way.attrib['timestamp'],
            'verification_status':'draft', 'verified_at':None}})
    collection = {'type':'FeatureCollection','source':'© OpenStreetMap contributors','license':'ODbL-1.0',
                  'imported_at':datetime.now(timezone.utc).isoformat(), 'features':features}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(collection,ensure_ascii=False,indent=2)+'\n')
    print(f'Imported {len(features)} draft road segments to {args.output}')


if __name__ == '__main__':
    main()
