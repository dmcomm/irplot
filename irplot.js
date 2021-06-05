
function LineMaker(pulse, height, yStep) {
    let values = [];
    let labels = [];
    let y = 0;
    let rows = 0;

    function add(durations, name, label) {
        let x = 0;
        for (let i = 0; i < durations.length; i ++) {
            values.push({name: name, x: x, y: y});
            x += durations[i] - pulse;
            values.push({name: name, x: x, y: y + height});
            x += pulse;
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
    
    return {add: add, values: values, labels: labels, makeAxis: makeAxis, count: function(){return rows;} };
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
    let LM = LineMaker(1, 10, 15);
    let config = readConfigFromDocument();
    for (let i = 0; i < config.selection.length; i ++) {
        let id = config.selection[i].id;
        let label = id;
        if (config.label === "shotSizeA" && records[id].shotSizeA) {
            label = id + " " + records[id].shotSizeA;
        }
        if (config.label === "wasHitA" && records[id].wasHitA) {
            label = id + " " + records[id].wasHitA;
        }
        let dursA = selectPacket(records[id].A, config.packet);
        let dursB = selectPacket(records[id].B, config.packet);
        if (config.channel === "A") {
            LM.add(dursA, id + " (A)", label);
        } else if (config.channel === "B") {
            LM.add(dursB, id + " (B)", label);
        } else if (config.channel === "below") {
            LM.add(dursA, id + " (A)", label + " (A)");
            LM.add(dursB, id + " (B)", label + " (B)");
        } else {
            //overlap
            LM.add(dursA, id + " (A)", null);
            LM.add(dursB, id + " (B)", label);
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
