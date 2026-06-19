"""Simulação de uma Cloud-Fog RAN com split funcional 7.2 fixo."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import simpy


@dataclass
class PacketResult:
    ru: str
    fog: str
    packet_id: int
    created_at_us: float
    fronthaul_latency_us: float
    end_to_end_latency_us: float


class Link:
    def __init__(
        self,
        env: simpy.Environment,
        capacity_gbps: float,
        distance_km: float,
        propagation_us_per_km: float,
        switching_delay_us: float,
    ) -> None:
        self.env = env
        self.capacity_gbps = capacity_gbps
        self.distance_km = distance_km
        self.propagation_us_per_km = propagation_us_per_km
        self.switching_delay_us = switching_delay_us
        self.resource = simpy.Resource(env, capacity=1)
        self.busy_time_us = 0.0

    def transmit(self, packet_size_bytes: int):
        transmission_us = packet_size_bytes * 8.0 / (self.capacity_gbps * 1000.0)
        propagation_us = self.distance_km * self.propagation_us_per_km
        with self.resource.request() as request:
            yield request
            self.busy_time_us += transmission_us
            yield self.env.timeout(transmission_us)
        yield self.env.timeout(propagation_us + self.switching_delay_us)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def validate_config(config: dict[str, Any]) -> list[str]:
    scenario = config["scenario"]
    errors: list[str] = []
    if str(scenario["functional_split"]) != "7.2":
        errors.append("O functional_split deve permanecer fixo em 7.2.")
    if len(config["rus"]) != 4:
        errors.append("A topologia deve possuir exatamente 4 RUs e 4 Fogs.")
    if config["power_watts"]["fog"] * 6 != config["power_watts"]["cloud"]:
        errors.append("Cada Fog deve consumir 1/6 da potência da Cloud.")

    fogs = {ru["fog"] for ru in config["rus"]}
    if len(fogs) != 4:
        errors.append("Cada RU deve estar associada a um Fog exclusivo.")

    minimum = scenario["fronthaul_bandwidth_min_gbps"]
    maximum = scenario["fronthaul_bandwidth_max_gbps"]
    for ru in config["rus"]:
        if not minimum <= ru["offered_load_gbps"] <= maximum:
            errors.append(
                f'{ru["id"]}: carga do split 7.2 fora de {minimum:g}-{maximum:g} Gbps.'
            )
        if not minimum <= ru["fronthaul_capacity_gbps"] <= maximum:
            errors.append(
                f'{ru["id"]}: capacidade do fronthaul fora de '
                f"{minimum:g}-{maximum:g} Gbps."
            )
        if ru["offered_load_gbps"] > ru["fronthaul_capacity_gbps"]:
            errors.append(f'{ru["id"]}: carga maior que a capacidade do fronthaul.')
    return errors


def build_graph(config: dict[str, Any]) -> nx.DiGraph:
    graph = nx.DiGraph()
    cloud_id = config["cloud"]["id"]
    graph.add_node(cloud_id, kind="cloud")
    for ru in config["rus"]:
        graph.add_node(ru["id"], kind="ru")
        graph.add_node(ru["fog"], kind="fog")
        graph.add_edge(
            ru["id"],
            ru["fog"],
            kind="fronthaul",
            capacity_gbps=ru["fronthaul_capacity_gbps"],
            distance_km=ru["fronthaul_distance_km"],
        )
        graph.add_edge(
            ru["fog"],
            cloud_id,
            kind="midhaul",
            capacity_gbps=ru["midhaul_capacity_gbps"],
            distance_km=ru["midhaul_distance_km"],
        )
    return graph


def simulate(config: dict[str, Any]) -> tuple[dict[str, Any], list[PacketResult]]:
    scenario = config["scenario"]
    duration_us = float(scenario["simulation_duration_us"])
    packet_size_bytes = int(scenario["packet_size_bytes"])
    propagation = float(scenario["optical_propagation_us_per_km"])
    cloud_delay = float(config["cloud"]["processing_delay_us"])
    env = simpy.Environment()
    packet_results: list[PacketResult] = []
    links: dict[str, tuple[Link, Link]] = {}

    for ru in config["rus"]:
        links[ru["id"]] = (
            Link(
                env,
                ru["fronthaul_capacity_gbps"],
                ru["fronthaul_distance_km"],
                propagation,
                ru["fronthaul_switching_delay_us"],
            ),
            Link(
                env,
                ru["midhaul_capacity_gbps"],
                ru["midhaul_distance_km"],
                propagation,
                ru["midhaul_switching_delay_us"],
            ),
        )

    def deliver_packet(ru: dict[str, Any], packet_id: int, created_at: float):
        fronthaul, midhaul = links[ru["id"]]
        yield env.process(fronthaul.transmit(packet_size_bytes))
        yield env.timeout(float(ru["fog_processing_delay_us"]))
        fronthaul_done = env.now
        yield env.process(midhaul.transmit(packet_size_bytes))
        yield env.timeout(cloud_delay)
        packet_results.append(
            PacketResult(
                ru=ru["id"],
                fog=ru["fog"],
                packet_id=packet_id,
                created_at_us=created_at,
                fronthaul_latency_us=fronthaul_done - created_at,
                end_to_end_latency_us=env.now - created_at,
            )
        )

    def generate_traffic(ru: dict[str, Any]):
        interval_us = packet_size_bytes * 8.0 / (ru["offered_load_gbps"] * 1000.0)
        packet_id = 0
        while env.now < duration_us:
            env.process(deliver_packet(ru, packet_id, env.now))
            packet_id += 1
            yield env.timeout(interval_us)

    for ru in config["rus"]:
        env.process(generate_traffic(ru))
    env.run(until=duration_us + 1000.0)

    latency_limit = float(scenario["fronthaul_latency_limit_us"])
    per_ru: dict[str, Any] = {}
    all_fronthaul = [item.fronthaul_latency_us for item in packet_results]
    all_end_to_end = [item.end_to_end_latency_us for item in packet_results]

    for ru in config["rus"]:
        rows = [item for item in packet_results if item.ru == ru["id"]]
        latencies = [item.fronthaul_latency_us for item in rows]
        fronthaul, midhaul = links[ru["id"]]
        per_ru[ru["id"]] = {
            "fog": ru["fog"],
            "packets_delivered": len(rows),
            "offered_load_gbps": ru["offered_load_gbps"],
            "fronthaul_capacity_gbps": ru["fronthaul_capacity_gbps"],
            "fronthaul_utilization": ru["offered_load_gbps"]
            / ru["fronthaul_capacity_gbps"],
            "fronthaul_latency_avg_us": statistics.fmean(latencies),
            "fronthaul_latency_p95_us": percentile(latencies, 0.95),
            "fronthaul_latency_max_us": max(latencies),
            "fronthaul_busy_time_us": fronthaul.busy_time_us,
            "midhaul_busy_time_us": midhaul.busy_time_us,
            "latency_compliant": max(latencies) <= latency_limit,
        }

    power = config["power_watts"]
    line_cards = len(config["rus"]) * 2
    total_power_watts = (
        power["cloud"]
        + len(config["rus"]) * power["fog"]
        + line_cards * power["line_card"]
        + power["olt"]
    )
    summary = {
        "scenario": scenario["name"],
        "functional_split": scenario["functional_split"],
        "topology": {
            "clouds": 1,
            "fogs": 4,
            "rus": 4,
            "paths": [
                nx.shortest_path(build_graph(config), ru["id"], config["cloud"]["id"])
                for ru in config["rus"]
            ],
        },
        "simulation_duration_us": duration_us,
        "packets_delivered": len(packet_results),
        "fronthaul_latency_limit_us": latency_limit,
        "fronthaul_latency_avg_us": statistics.fmean(all_fronthaul),
        "fronthaul_latency_p95_us": percentile(all_fronthaul, 0.95),
        "fronthaul_latency_max_us": max(all_fronthaul),
        "end_to_end_latency_avg_us": statistics.fmean(all_end_to_end),
        "end_to_end_latency_p95_us": percentile(all_end_to_end, 0.95),
        "power": {
            "cloud_watts": power["cloud"],
            "fog_total_watts": len(config["rus"]) * power["fog"],
            "line_cards": line_cards,
            "line_cards_total_watts": line_cards * power["line_card"],
            "olt_watts": power["olt"],
            "total_watts": total_power_watts,
            "energy_wh_during_simulation": total_power_watts
            * duration_us
            / 3_600_000_000.0,
        },
        "per_ru": per_ru,
    }
    summary["compliant"] = all(
        item["latency_compliant"] for item in per_ru.values()
    )
    return summary, packet_results


def write_csv(path: Path, rows: list[PacketResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=PacketResult.__annotations__)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def generate_plots(
    config: dict[str, Any],
    summary: dict[str, Any],
    packets: list[PacketResult],
    plots_dir: Path,
) -> list[Path]:
    plots_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    colors = {
        "cloud": "#355070",
        "fog": "#6D597A",
        "ru": "#E56B6F",
        "fronthaul": "#EAAC8B",
        "midhaul": "#4C956C",
    }

    graph = build_graph(config)
    positions: dict[str, tuple[float, float]] = {
        config["cloud"]["id"]: (2.25, 2.0)
    }
    for index, ru in enumerate(config["rus"]):
        positions[ru["id"]] = (index * 1.5, 0.0)
        positions[ru["fog"]] = (index * 1.5, 1.0)

    plt.figure(figsize=(10, 5.5))
    node_colors = [colors[graph.nodes[node]["kind"]] for node in graph.nodes]
    edge_colors = [
        colors[graph.edges[edge]["kind"]] for edge in graph.edges
    ]
    nx.draw_networkx(
        graph,
        positions,
        node_color=node_colors,
        edge_color=edge_colors,
        node_size=1900,
        font_size=9,
        font_color="white",
        arrows=True,
        arrowsize=18,
    )
    edge_labels = {
        edge: (
            f'{attributes["capacity_gbps"]:g} Gbps\n'
            f'{attributes["distance_km"]:g} km'
        )
        for edge, attributes in graph.edges.items()
    }
    nx.draw_networkx_edge_labels(
        graph, positions, edge_labels=edge_labels, font_size=8
    )
    plt.title("Topologia Cloud–Fog RAN com split funcional 7.2")
    plt.axis("off")
    plt.tight_layout()
    path = plots_dir / "01_topologia_split72.png"
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()
    generated.append(path)

    ru_ids = list(summary["per_ru"])
    averages = [
        summary["per_ru"][ru]["fronthaul_latency_avg_us"] for ru in ru_ids
    ]
    p95_values = [
        summary["per_ru"][ru]["fronthaul_latency_p95_us"] for ru in ru_ids
    ]
    maximums = [
        summary["per_ru"][ru]["fronthaul_latency_max_us"] for ru in ru_ids
    ]
    x_positions = list(range(len(ru_ids)))
    width = 0.24
    plt.figure(figsize=(9, 5.5))
    plt.bar(
        [x - width for x in x_positions],
        averages,
        width,
        label="Média",
        color="#4C956C",
    )
    plt.bar(x_positions, p95_values, width, label="P95", color="#F4A261")
    plt.bar(
        [x + width for x in x_positions],
        maximums,
        width,
        label="Máxima",
        color="#E76F51",
    )
    plt.axhline(
        summary["fronthaul_latency_limit_us"],
        color="#C1121F",
        linestyle="--",
        linewidth=2,
        label="Limite de 250 μs",
    )
    plt.xticks(x_positions, ru_ids)
    plt.ylabel("Latência (μs)")
    plt.title("Latência de fronthaul RU–Fog")
    plt.ylim(0, summary["fronthaul_latency_limit_us"] * 1.15)
    plt.grid(axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    path = plots_dir / "02_latencia_fronthaul.png"
    plt.savefig(path, dpi=180)
    plt.close()
    generated.append(path)

    offered = [
        summary["per_ru"][ru]["offered_load_gbps"] for ru in ru_ids
    ]
    capacities = [
        summary["per_ru"][ru]["fronthaul_capacity_gbps"] for ru in ru_ids
    ]
    plt.figure(figsize=(9, 5.5))
    plt.bar(
        [x - width / 2 for x in x_positions],
        offered,
        width,
        label="Carga oferecida",
        color="#E56B6F",
    )
    plt.bar(
        [x + width / 2 for x in x_positions],
        capacities,
        width,
        label="Capacidade do enlace",
        color="#355070",
    )
    plt.axhspan(5, 10, color="#4C956C", alpha=0.10, label="Faixa 5–10 Gbps")
    plt.xticks(x_positions, ru_ids)
    plt.ylabel("Banda (Gbps)")
    plt.title("Carga e capacidade do fronthaul 7.2")
    plt.ylim(0, max(capacities) * 1.2)
    plt.grid(axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    path = plots_dir / "03_banda_fronthaul.png"
    plt.savefig(path, dpi=180)
    plt.close()
    generated.append(path)

    power = summary["power"]
    power_labels = ["Cloud", "4 Fogs", "8 Line Cards", "OLT"]
    power_values = [
        power["cloud_watts"],
        power["fog_total_watts"],
        power["line_cards_total_watts"],
        power["olt_watts"],
    ]
    plt.figure(figsize=(8.5, 5.5))
    bars = plt.bar(
        power_labels,
        power_values,
        color=["#355070", "#6D597A", "#EAAC8B", "#4C956C"],
    )
    plt.bar_label(bars, labels=[f"{value:g} W" for value in power_values], padding=4)
    plt.ylabel("Potência (W)")
    plt.title(f'Consumo de potência — total de {power["total_watts"]:g} W')
    plt.ylim(0, max(power_values) * 1.2)
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    path = plots_dir / "04_consumo_potencia.png"
    plt.savefig(path, dpi=180)
    plt.close()
    generated.append(path)

    plt.figure(figsize=(10, 5.5))
    for ru_id in ru_ids:
        ru_packets = [packet for packet in packets if packet.ru == ru_id]
        plt.plot(
            [packet.created_at_us / 1000.0 for packet in ru_packets],
            [packet.fronthaul_latency_us for packet in ru_packets],
            label=ru_id,
            linewidth=1.3,
        )
    plt.axhline(
        summary["fronthaul_latency_limit_us"],
        color="#C1121F",
        linestyle="--",
        linewidth=2,
        label="Limite de 250 μs",
    )
    plt.xlabel("Tempo da simulação (ms)")
    plt.ylabel("Latência de fronthaul (μs)")
    plt.title("Evolução temporal da latência por RU")
    plt.ylim(0, summary["fronthaul_latency_limit_us"] * 1.15)
    plt.grid(alpha=0.25)
    plt.legend(ncol=3)
    plt.tight_layout()
    path = plots_dir / "05_latencia_no_tempo.png"
    plt.savefig(path, dpi=180)
    plt.close()
    generated.append(path)

    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="scenarios/split72_topology.json")
    parser.add_argument("--output", default="results/split72_results.json")
    parser.add_argument("--csv", default=None)
    parser.add_argument(
        "--plots-dir",
        default="results/plots",
        help="Diretório no qual os gráficos PNG serão gravados.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Retorna erro se banda, topologia ou latência violarem os requisitos.",
    )
    args = parser.parse_args()

    with Path(args.config).open(encoding="utf-8") as config_file:
        config = json.load(config_file)

    errors = validate_config(config)
    if errors:
        for error in errors:
            print(f"ERRO: {error}", file=sys.stderr)
        return 2

    summary, packets = simulate(config)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if args.csv:
        write_csv(Path(args.csv), packets)
    generated_plots = generate_plots(
        config, summary, packets, Path(args.plots_dir)
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("Gráficos gerados:")
    for plot in generated_plots:
        print(f"- {plot}")
    if args.strict and not summary["compliant"]:
        print("ERRO: o limite de latência do fronthaul foi violado.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
