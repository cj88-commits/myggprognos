# Geographic benchmark — before

Computed fresh at `2026-08-07T07:29:08.897997+00:00` from real static features (`data/static/cell_features.json`) and a live weather fetch for 55 benchmark locations (`forecast/benchmarks/locations.json`), all evaluated at the same instant so differences are attributable to geography/weather-history, not time-of-day. Full data: `data/generated/diagnostics/geographic-benchmark-before.csv`.

## Contrast pairs

No target ratios are hard-coded here (per spec) -- these numbers are reported as evidence, not asserted against a threshold.

| Contrast | Higher-expected location | population_potential | Lower-expected location | population_potential | ratio | final_risk ratio |
|---|---|---|---|---|---|---|
| Dalarna skog / Stockholm centrum | Dalarna skog (Alvdalen) | 37.4 | Stockholm centrum | 34.0 | 1.10x | 1.12x |
| Siljan strand / Stockholm centrum | Siljan strand (Rattvik) | 35.9 | Stockholm centrum | 34.0 | 1.05x | 1.11x |
| Osterfarnebo (Lower Dalalven) / Stockholm centrum | Osterfarnebo | 40.8 | Stockholm centrum | 34.0 | 1.20x | 1.26x |
| Norrbotten vat barrskog / Stockholm centrum | Norrbotten vat barrskog (Jokkmokk) | 36.6 | Stockholm centrum | 34.0 | 1.08x | 1.14x |
| Norrbotten vatmark / Harjedalen fjall | Norrbotten vatmark (Muddus/Sjaunja) | 41.9 | Harjedalen fjall (Funasdalen) | 33.2 | 1.26x | 1.17x |
| Vanern strand / Vanern oppet vatten | Vanern strand (Lidkoping) | 39.9 | Vanern oppet vatten | 32.6 | 1.22x | 1.21x |
| Store Mosse (wetland) / Malardalen jordbruksbygd (farmland) | Store Mosse nationalpark | 47.7 | Malardalen jordbruksbygd (Enkoping) | 32.7 | 1.46x | 1.48x |
| Vasterbottens inland (forest) / Stockholm centrum | Vasterbottens inland (Lycksele) | 34.9 | Stockholm centrum | 34.0 | 1.03x | 1.08x |
| Bohuslan (exposed coast) / Varmland skog och sjo (sheltered lake) | Varmland skog och sjo (Sunne, Frykensjoarna) | 36.3 | Bohuslan (Fjallbacka) | 35.8 | 1.01x | 1.00x |

## Distribution across all benchmark locations

- `population_potential` (Myggläge): min 18.0, p25 33.3, median 35.4, p75 36.8, max 47.7, mean 34.8
- `final_risk` (Myggrisk, this instant): min 5.4, p25 11.0, median 11.8, p75 12.5, max 15.9, mean 11.7

## Full table

| Location | Category | forest | wetland | water | urban | dist_water_km | elevation_m | pop_potential | activity | exposure | final_risk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Stockholm centrum | urban centre | 0.19 | 0.00 | 0.20 | 0.51 | 0.3 | 9 | 34.0 | 0.0 | 59.7 | 11.2 |
| Stockholms skargard (Vaxholm) | archipelago | 0.31 | 0.01 | 0.53 | 0.07 | 0.4 | 23 | 35.1 | 0.0 | 66.4 | 12.0 |
| Uppsala | major city | 0.20 | 0.00 | 0.01 | 0.40 | 1.1 | 12 | 35.6 | 0.0 | 54.8 | 11.5 |
| Osterfarnebo | dense inland forest | 0.37 | 0.27 | 0.40 | 0.01 | 0.1 | 52 | 40.8 | 0.2 | 69.6 | 14.2 |
| Linkoping | major city | 0.38 | 0.02 | 0.01 | 0.24 | 1.7 | 74 | 36.8 | 0.0 | 53.4 | 11.8 |
| Store Mosse nationalpark | wetland / floodplain | 0.52 | 0.54 | 0.01 | 0.02 | 1.3 | 175 | 47.7 | 0.0 | 61.9 | 15.9 |
| Goteborg kustlinje | exposed west coast | 0.34 | 0.01 | 0.01 | 0.46 | 2.7 | 47 | 36.1 | 0.0 | 40.8 | 10.8 |
| Bohuslan (Fjallbacka) | exposed west coast | 0.28 | 0.02 | 0.27 | 0.05 | 0.3 | 9 | 35.8 | 0.6 | 66.9 | 12.4 |
| Malmo | major city | 0.14 | 0.00 | 0.10 | 0.60 | 0.1 | 8 | 32.8 | 0.0 | 58.9 | 10.8 |
| Vanern strand (Lidkoping) | lake shore | 0.31 | 0.02 | 0.14 | 0.13 | 1.3 | 60 | 39.9 | 1.1 | 57.8 | 13.4 |
| Vattern strand (Granna) | lake shore | 0.22 | 0.01 | 0.53 | 0.04 | 0.1 | 92 | 32.4 | 0.0 | 67.3 | 11.1 |
| Gotland (Visby) | island | 0.31 | 0.00 | 0.14 | 0.25 | 1.7 | 50 | 34.8 | 0.0 | 52.0 | 11.1 |
| Gotland (Faro) | island / exposed coast | 0.35 | 0.06 | 0.21 | 0.03 | 0.3 | 7 | 39.4 | 0.0 | 68.2 | 13.5 |
| Oland (Borgholm) | island | 0.13 | 0.02 | 0.56 | 0.05 | 0.1 | 7 | 35.7 | 0.0 | 66.1 | 12.2 |
| Oland (Ottenby, sodra udden) | island / exposed coast | 0.12 | 0.07 | 0.45 | 0.01 | 0.9 | 8 | 32.2 | 0.0 | 60.2 | 10.7 |
| Umea | northern coast city | 0.28 | 0.00 | 0.08 | 0.34 | 0.3 | 6 | 33.3 | 0.0 | 63.1 | 11.2 |
| Lulea | northern coast city | 0.33 | 0.02 | 0.24 | 0.28 | 0.7 | 13 | 35.5 | 0.0 | 61.7 | 11.8 |
| Kiruna | far north | 0.44 | 0.07 | 0.07 | 0.22 | 1.3 | 552 | 28.0 | 0.0 | 58.2 | 9.2 |
| Abisko | far north / mountain | 0.36 | 0.00 | 0.34 | 0.01 | 0.7 | 372 | 25.6 | 7.9 | 65.5 | 10.3 |
| Are (fjallomrade) | mountain region | 0.41 | 0.05 | 0.01 | 0.03 | 3.0 | 1006 | 20.5 | 0.0 | 45.9 | 6.3 |
| Sarek nationalpark | mountain region / far north | 0.00 | 0.00 | 0.00 | 0.00 | 3.3 | 1229 | 18.0 | 0.1 | 39.4 | 5.4 |
| Smaland jordbruksbygd (Vaxjo) | farmland | 0.48 | 0.07 | 0.08 | 0.18 | 0.5 | 172 | 36.9 | 0.0 | 66.4 | 12.6 |
| Skane jordbruksbygd (Ystad) | farmland | 0.08 | 0.01 | 0.50 | 0.22 | 0.1 | 2 | 32.6 | 0.0 | 63.3 | 11.0 |
| Dalalven flodslatt | floodplain | 0.82 | 0.14 | 0.01 | 0.06 | 2.5 | 12 | 40.5 | 0.1 | 53.5 | 13.0 |
| Tornedalen (alvdal, floodplain) | floodplain / far north | 0.35 | 0.04 | 0.19 | 0.10 | 0.6 | 9 | 35.9 | 0.0 | 64.8 | 12.2 |
| Vastkusten skargard (Marstrand) | archipelago | 0.09 | 0.01 | 0.65 | 0.02 | 0.1 | 11 | 33.4 | 0.1 | 65.9 | 11.4 |
| Ostkusten skargard (Sandhamn) | archipelago | 0.26 | 0.01 | 0.68 | 0.00 | 0.1 | 9 | 34.3 | 0.0 | 68.4 | 11.8 |
| Sundsvall kustnara | northern coast city | 0.44 | 0.01 | 0.06 | 0.29 | 0.1 | 18 | 34.9 | 0.0 | 67.0 | 11.9 |
| Ornskoldsvik | northern coast city | 0.52 | 0.01 | 0.09 | 0.20 | 1.1 | 58 | 35.6 | 0.0 | 61.5 | 11.8 |
| Vasterbottens inland (Lycksele) | dense inland forest | 0.59 | 0.06 | 0.14 | 0.14 | 0.1 | 217 | 34.9 | 0.0 | 70.8 | 12.1 |
| Smalandsskog (Uppvidinge) | dense inland forest | 0.85 | 0.12 | 0.06 | 0.03 | 0.5 | 256 | 39.3 | 0.0 | 73.3 | 13.8 |
| Vasteras | major city | 0.18 | 0.01 | 0.37 | 0.29 | 0.1 | 3 | 35.8 | 0.0 | 63.6 | 12.0 |
| Orebro | major city | 0.27 | 0.06 | 0.05 | 0.35 | 1.3 | 31 | 33.9 | 0.3 | 54.2 | 11.0 |
| Kristianstad (vatmarker) | wetland / floodplain | 0.14 | 0.14 | 0.26 | 0.16 | 0.1 | 0 | 38.7 | 0.0 | 64.9 | 13.1 |
| Hjalstaviken (vatmark) | wetland / floodplain | 0.49 | 0.02 | 0.03 | 0.06 | 2.5 | 28 | 39.1 | 0.2 | 49.5 | 12.3 |
| Stockholm forort (Tyreso) | urban suburb | 0.47 | 0.03 | 0.08 | 0.25 | 1.6 | 53 | 35.9 | 0.0 | 55.3 | 11.6 |
| Mora (Siljan) | lake shore | 0.34 | 0.04 | 0.30 | 0.17 | 0.1 | 166 | 35.2 | 0.0 | 67.2 | 12.1 |
| Siljan strand (Rattvik) | lake shore | 0.63 | 0.03 | 0.08 | 0.11 | 0.8 | 193 | 35.9 | 0.9 | 67.4 | 12.5 |
| Dalarna skog (Alvdalen) | boreal forest | 0.76 | 0.05 | 0.06 | 0.07 | 1.3 | 287 | 37.4 | 0.1 | 64.3 | 12.6 |
| Varmland skog och sjo (Sunne, Frykensjoarna) | lake shore | 0.59 | 0.02 | 0.13 | 0.07 | 1.4 | 132 | 36.3 | 1.3 | 60.8 | 12.4 |
| Umea inland (Vindeln) | dense inland forest | 0.76 | 0.08 | 0.07 | 0.05 | 1.6 | 243 | 35.3 | 0.0 | 61.6 | 11.8 |
| Skelleftea | northern coast city | 0.47 | 0.02 | 0.05 | 0.21 | 0.7 | 23 | 34.7 | 0.0 | 64.3 | 11.7 |
| Overtornea (Tornealven) | floodplain / far north | 0.51 | 0.05 | 0.12 | 0.05 | 1.3 | 122 | 34.4 | 0.0 | 61.3 | 11.4 |
| Kiruna lagland (Torneträsk lagland) | far north lowland | 0.57 | 0.03 | 0.04 | 0.00 | 0.7 | 473 | 28.4 | 0.0 | 68.1 | 9.7 |
| Vanern oppet vatten | major open lake | 0.00 | 0.00 | 1.00 | 0.00 | 0.1 | 42 | 32.6 | 0.0 | 65.0 | 11.0 |
| Malaren oppet vatten | major open lake | 0.36 | 0.02 | 0.27 | 0.02 | 0.9 | 27 | 39.7 | 0.0 | 64.1 | 13.4 |
| Vattern oppet vatten | major open lake | 0.00 | 0.00 | 1.00 | 0.00 | 0.1 | 88 | 28.2 | 0.0 | 65.0 | 9.5 |
| Norrbotten vatmark (Muddus/Sjaunja) | wetland | 0.68 | 0.51 | 0.08 | 0.00 | 1.9 | 396 | 41.9 | 0.0 | 58.0 | 13.7 |
| Vasterbotten vat skog (Vilhelmina) | northern wet forest | 0.56 | 0.17 | 0.24 | 0.07 | 0.3 | 358 | 35.5 | 0.0 | 70.2 | 12.3 |
| Norrbotten vat barrskog (Jokkmokk) | northern wet forest | 0.74 | 0.13 | 0.06 | 0.07 | 0.5 | 243 | 36.6 | 0.0 | 71.3 | 12.8 |
| Skane jordbruksbygd (Lund) | farmland | 0.19 | 0.00 | 0.00 | 0.33 | 1.9 | 28 | 34.2 | 0.0 | 47.2 | 10.6 |
| Malardalen jordbruksbygd (Enkoping) | farmland | 0.33 | 0.01 | 0.01 | 0.16 | 1.1 | 23 | 32.7 | 0.0 | 59.1 | 10.8 |
| Hoga Kusten (exponerad kust) | exposed coast | 0.58 | 0.02 | 0.22 | 0.03 | 0.3 | 16 | 35.4 | 0.0 | 71.1 | 12.3 |
| Harjedalen fjall (Funasdalen) | mountain region | 0.70 | 0.10 | 0.15 | 0.03 | 0.1 | 568 | 33.2 | 0.0 | 73.9 | 11.7 |
| Kalixalvens flodslatt | floodplain / far north | 0.47 | 0.09 | 0.15 | 0.16 | 0.4 | 14 | 37.4 | 0.0 | 67.3 | 12.8 |
