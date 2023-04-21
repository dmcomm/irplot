import json

with open("irdata.json") as f:
    for item in json.load(f)["data"]:
        print(item["id"], "\t", len(item["A"]), "\t", len(item.get("B", [])))
