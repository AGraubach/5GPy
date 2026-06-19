# 5GPy

## Cenário Docker: split funcional 7.2

Este repositório inclui um cenário reproduzível com:

- 1 Cloud de 600 W;
- 4 Fogs de 100 W cada (1/6 da potência da Cloud);
- 4 RUs, uma por Fog, configuradas para 20 MHz e MIMO 2x2;
- split funcional fixo em 7.2;
- carga de fronthaul de 5 Gbps por RU;
- enlaces de fronthaul de 10 Gbps;
- propagação óptica de 5 us/km;
- validação automática do limite de 250 us no trecho RU-Fog.

Execute com Docker Compose:

```bash
docker compose up --build
```

Ou apenas com Docker:

```bash
docker build -t 5gpy-split72 .
docker run --rm -v "${PWD}/results:/app/results" 5gpy-split72
```

Os resultados agregados são gravados em
`results/split72_results.json`, e as amostras por pacote em
`results/split72_packets.csv`. A pasta `results/plots` recebe
automaticamente:

- o diagrama da topologia Cloud–Fog RAN;
- a comparação entre latência média, P95, máxima e o limite de 250 us;
- a carga oferecida e a capacidade de banda por RU;
- o consumo de potência por componente;
- a evolução temporal da latência por RU.

Os parâmetros podem ser alterados em
`scenarios/split72_topology.json`. O modo `--strict` faz o container
retornar erro quando a configuração sai da faixa de 5-10 Gbps ou quando
a latência de fronthaul ultrapassa 250 us.

Dependencies:

5GPy runs with Python 3.6.9.

5GPy uses Networkx Python module to implement graphs. Install it using the following command:

-pip install networkx

All simulation configurations must be put at:

-configurations.xml

The initialization of a simulation is done at:

-simulation.py

To run a simulation, execute:

-python3 simulation.py

The classes representing the network topology elements are within:

-network.py

Utility methods can be found and must be placed at:

-utiliy.py

Please, when using 5GPy in your paper, thesis or dissertation, it is mandatory to cite the following reference:

@article{tinini20195gpy,
title={5GPy: A SimPy-based simulator for performance evaluations in 5G hybrid Cloud-Fog RAN architectures},
author={Tinini, Rodrigo Izidoro and dos Santos, Matias Rom{\'a}rio Pinheiro and Figueiredo, Gustavo Bittencourt and Batista, Daniel Mac{\^e}do},
journal={Simulation Modelling Practice and Theory},
pages={102030},
year={2019},
publisher={Elsevier}
}

If you have any questions, please contact me at: tinini at fei dot edu dot br
