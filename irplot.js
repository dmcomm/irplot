
function LineMaker(height, yStep) {
    let values = [];
    let markers = [];
    let labels = [];
    let y = 0;
    let rows = 0;

    function add(durations, name, label, decode) {
        let x = 0;
        let prevXtoOn = -2000;
        let isOn = false;
        values.push({name: name, x: -100, y: y});
        for (let i = 0; i <= durations.length; i ++) {
            if (isOn) {
                values.push({name: name, x: x, y: y + height});
            } else {
                values.push({name: name, x: x, y: y});
                if ((decode === "ic" || decode === "ics") && x - prevXtoOn > 860) {
                    for (let j = 1; j <= 8; j ++) {
                        markers.push({x: x + 100*j, y: y + height/2});
                    }
                    prevXtoOn = x;
                }
            }
            if (i < durations.length) {
                x += durations[i];
            }
            isOn = !isOn;
        }
        if (label != null) {
            labels.push({y: y, label: label});
            y -= yStep;
            rows += 1;
        }
    }
    
    function makeAxis() {
        if (labels.length == 0) {
            return {"title": null};
        }
        let values = [];
        let labelExpr = "";
        for (let i = 0; i < labels.length - 1; i ++) {
            values.push(labels[i].y);
            labelExpr += "datum.value == " + labels[i].y + " ? '" + labels[i].label + "' : "; 
        }
        values.push(labels[labels.length - 1].y);
        labelExpr += "'" + labels[labels.length - 1].label + "'";
        return {
            "labelExpr": labelExpr,
            "values": values,
            "labelFlush": false,
            "title": null
        };
    }
    
    return {
        add: add,
        values: values,
        markers: markers,
        labels: labels,
        makeAxis: makeAxis,
        count: function() { return rows; }
    };
}

function selectPacket(durations, packetNum) {
    if (packetNum == 0) {
        return durations;
    }
    let result = [];
    let packetCursor = 0;
    for (let i = 0; i < durations.length; i ++) {
        let dur = durations[i];
        if (i == 0 || dur > 15000) {
            dur = 0;
            packetCursor ++;
        }
        if (packetCursor == packetNum) {
            result.push(dur);
        }
    }
    return result;
}

function insertOnTimes(durations, pulse) {
    if (durations.length == 0) {
        return [];
    }
    let result = [durations[0]];
    for (let i = 1; i < durations.length; i ++) {
        if (durations[i] > pulse) {
            result.push(pulse);
            result.push(durations[i] - pulse);
        } else {
            result.push(pulse/10);
            result.push(pulse/10);
        }
    }
    result.push(pulse);
    return result;
}

function readConfigFromDocument() {
    let config = {};
    config.packet = $("#packetNum").val();
    if ($("#channelA").prop("checked")) {
        config.channel = "A";
    } else if ($("#channelB").prop("checked")) {
        config.channel = "B";
    } else if ($("#channelBelow").prop("checked")) {
        config.channel = "below";
    } else {
        config.channel = "overlap";
    }
    if ($("#ylabelSizes").prop("checked")) {
        config.label = "shotSizeA";
    } else if ($("#ylabelWasHit").prop("checked")) {
        config.label = "wasHitA";
    } else {
        config.label = "id";
    }
    config.selection = [];
    $("input[name=weight]").each(function() {
        let weightBox = $(this);
        let id = weightBox.prop("id");
        let weight = weightBox.val();
        if (weight != 0) {
            config.selection.push({id: id, weight: weight});
        }
    });
    config.selection.sort(function(a, b){return a.weight - b.weight});
    return config;
}

function applyConfigToDocument(config) {
    $("#packetNum").val(config.packet);
    if (config.channel === "A") {
        $("#channelA").prop("checked");
    } else if (config.channel === "B") {
        $("#channelB").prop("checked");
    } else if (config.channel === "below") {
        $("#channelBelow").prop("checked", true);
    } else {
        $("#channelOverlap").prop("checked", true);
    }
    if (config.label === "shotSizeA") {
        $("#ylabelSizes").prop("checked", true);
    } else if (config.label === "wasHitA") {
        $("#ylabelWasHit").prop("checked", true);
    } else {
        $("#ylabelID").prop("checked", true);
    }
    $("input[name=weight]").val(0);
    for (let i = 0; i < config.selection.length; i ++) {
        let item = config.selection[i];
        $("#" + item.id).val(item.weight);
    }
}

function plot(records) {
    let LM = LineMaker(10, 15);
    let config = readConfigFromDocument();
    for (let i = 0; i < config.selection.length; i ++) {
        let id = config.selection[i].id;
        let label = id;
        let decode = records[id].decode;
        if (config.label === "shotSizeA" && records[id].shotSizeA) {
            label = id + " " + records[id].shotSizeA;
        }
        if (config.label === "wasHitA" && records[id].wasHitA) {
            label = id + " " + records[id].wasHitA;
        }
        let dursA = records[id].A;
        let dursB = records[id].B;
        if (!dursB) {
            dursB = [];
        }
        dursA = selectPacket(dursA, config.packet);
        dursB = selectPacket(dursB, config.packet);
        if (!records[id].hasOnTimes) {
            dursA = insertOnTimes(dursA, 1);
            dursB = insertOnTimes(dursB, 1);
        }
        if (config.channel === "A") {
            LM.add(dursA, id + " (A)", label, decode);
        } else if (config.channel === "B") {
            LM.add(dursB, id + " (B)", label, decode);
        } else if (config.channel === "below") {
            LM.add(dursA, id + " (A)", label + " (A)", decode);
            LM.add(dursB, id + " (B)", label + " (B)", decode);
        } else {
            //overlap
            LM.add(dursA, id + " (A)", null, decode);
            LM.add(dursB, id + " (B)", label, decode);
        }
    }
    
    let axis = LM.makeAxis();
    let width = $(window).width() * 0.9;
    
    let vlSpec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.1.0.json",
        "description": "IR plot",
        "data": {
            "values": LM.values
        },
        "vconcat": [{
            "width": width,
            "height": LM.count() * 50 + 1,
            "layer": [{
                "mark": {
                    "type": "line",
                    "interpolate": "step-after"
                },
                "encoding": {
                    "x": {
                        "field": "x",
                        "type": "quantitative",
                        "scale": {"domain": {"param": "brush"}},
                        "axis": {"title": ""}
                    },
                    "y": {"field": "y", "type": "quantitative", "axis": axis},
                    "color": {"field": "name", "type": "nominal", "legend": null},
                }
             }, {
                "data": {
                    "values": LM.markers
                },
                "mark": {
                    "type": "point",
                    "size": 25,
                    "strokeWidth": 0.7,
                    "color": "black"
                },
                "encoding": {
                    "x": {
                        "field": "x",
                        "type": "quantitative",
                        "scale": {"domain": {"param": "brush"}}
                    },
                    "y": {"field": "y", "type": "quantitative"}
                }
             }]
         }, {
            "width": width,
            "height": LM.count() * 20 + 1,
            "params": [{
                "name": "brush",
                "select": {"type": "interval", "encodings": ["x"]}
            }],
            "mark": {
                "type": "line",
                "interpolate": "step-after"
            },
            "encoding": {
                "x": {
                    "field": "x",
                    "type": "quantitative",
                    "axis": {"title": "time (microseconds)"}
                },
                "y": {"field": "y", "type": "quantitative", "axis": axis},
                "color": {"field": "name", "type": "nominal", "legend": null},
            }
         }]
    };
    vegaEmbed('#vis', vlSpec);
}

$(document).ready(function() {
    let records = {}
    $.getJSON("irdata.json", function(data) {
        let recordsTbody = $("#records").find("tbody");
        for (let i = 0; i < data.data.length; i ++) {
            let record = data.data[i];
            let id = record.id;
            let tableRow = $("<tr>");
            if (id in records) {
                //can't use it twice
                tableRow.append(($("<td>")).append("x"));
            } else {
                //OK
                records[id] = record;
                let weightBox = $('<input type="number" name="weight" class="weight" min="0" value="0">');
                weightBox.prop("id", id);
                tableRow.append(($("<td>")).append(weightBox));
                //select something initially
                if (i < 2) {
                    weightBox.val(i + 1);
                }
            }
            tableRow.append(($("<td>")).text(id));
            tableRow.append(($("<td>")).text(record.shotSizeA));
            tableRow.append(($("<td>")).text(record.wasHitA));
            tableRow.append(($("<td>")).text(record.note));
            recordsTbody.append(tableRow);
        }
        plot(records);
    });
    $("#buttonPlot").click(function() {
        plot(records);
    });
    $("#buttonRefresh").click(function() {
        $("#configJson").val(
            JSON.stringify(readConfigFromDocument())
        );
    });
    $("#buttonApply").click(function() {
        applyConfigToDocument(JSON.parse($("#configJson").val()));
        plot(records);
    });
    $("#packetNum").on("input", function() {
        if ($("#packetNum").val() == 0) {
            $("#channelOverlap").prop("disabled", false);
        } else {
            if ($("#channelOverlap").prop("checked")) {
                $("#channelBelow").prop("checked", true);
            }
            $("#channelOverlap").prop("disabled", true);
        }
    });
});
