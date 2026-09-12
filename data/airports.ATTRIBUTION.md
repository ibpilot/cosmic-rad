# airports.dat — procedencia y licencia

`data/airports.dat` es una copia literal de
`https://github.com/jpatokal/openflights/blob/master/data/airports.dat`
(7698 aeropuertos), descargada el 2026-09-12.

Datos de **OpenFlights** (https://openflights.org/data.php), publicados bajo
**Open Database License (ODbL) 1.0** con los contenidos bajo **Database Contents
License (DbCL) 1.0**:

- https://opendatacommons.org/licenses/odbl/1-0/
- https://opendatacommons.org/licenses/dbcl/1-0/

La copia se guarda aquí porque la app la pedía en caliente a
`raw.githubusercontent.com`, que devuelve 503 cuando el fichero no está en la
caché del edge (`Backend.max_conn reached`). Servirla desde GitHub Pages del
propio repo la hace fiable y de paso quita una dependencia de terceros en
tiempo de ejecución.

Guardar el fichero aquí es **redistribución**, y la ODbL exige atribución: de
ahí este aviso. Si se actualiza la copia, mantener la fecha de descarga.
