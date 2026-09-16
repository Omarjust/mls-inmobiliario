"""Formato numérico para Latinoamérica.

El locale «es» que trae Django usa espacio fino como separador de miles
(410 000), convención de España. En Bolivia y la región se escribe 410.000.
"""

THOUSAND_SEPARATOR = "."
DECIMAL_SEPARATOR = ","
NUMBER_GROUPING = 3

DATE_FORMAT = "j \\d\\e F \\d\\e Y"
SHORT_DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "j \\d\\e F \\d\\e Y H:i"
SHORT_DATETIME_FORMAT = "d/m/Y H:i"
