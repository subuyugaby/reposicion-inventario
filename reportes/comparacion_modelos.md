# Comparación de modelos

Cada fila es una versión del Model Registry. El retador y el modelo vigente se miden en las mismas fechas de corte de evaluación, que ninguno usó para entrenar ni calibrar. Costo: costo de negocio del pedido sugerido con configs/costos.yaml.

| Versión | Tipo | Corte | Costo | Costo vigente | WAPE | WAPE vigente | Cobertura 80 % | Decisión | Motivo |
|---|---|---|---|---|---|---|---|---|---|
| v1 | perfil | 2017-01-02 | 7,440,190 | — | 0.205 | — | 75.5% | inicial | primer modelo vigente: baseline |
| v2 | lightgbm | 2017-01-02 | 5,811,949 | v1: 7,440,190 | 0.168 | 0.205 | 76.9% | promovido | mejora de costo 21.9%; WAPE 0.205 -> 0.168 |
| v3 | lightgbm | 2017-02-06 | 8,447,046 | v2: 8,171,736 | 0.239 | 0.239 | 69.1% | descartado | mejora de costo -3.4%, menor que el mínimo de 2% |
| v4 | lightgbm | 2017-03-06 | 5,492,914 | v2: 4,151,857 | 0.161 | 0.144 | 88.0% | descartado | mejora de costo -32.3%, menor que el mínimo de 2% |
| v5 | lightgbm | 2017-04-03 | 15,059,573 | v2: 4,647,387 | 0.347 | 0.146 | 83.0% | descartado | mejora de costo -224.0%, menor que el mínimo de 2% |
| v6 | lightgbm | 2017-05-01 | 5,759,116 | v2: 4,927,755 | 0.172 | 0.155 | 81.6% | descartado | mejora de costo -16.9%, menor que el mínimo de 2% |
| v7 | lightgbm | 2017-06-05 | 4,980,984 | v2: 5,272,865 | 0.148 | 0.158 | 78.3% | promovido | mejora de costo 5.5%; WAPE 0.158 -> 0.148 |
| v8 | lightgbm | 2017-07-03 | 4,182,215 | v7: 4,030,261 | 0.135 | 0.129 | 82.3% | descartado | mejora de costo -3.8%, menor que el mínimo de 2% |
| v9 | lightgbm | 2017-08-07 | 3,669,135 | v7: 3,806,720 | 0.118 | 0.118 | 81.8% | promovido | mejora de costo 3.6%; WAPE 0.118 -> 0.118 |
