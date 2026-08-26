"""Os modelos Pydantic da fronteira HTTP: o que entra e o que sai.

Separados das entidades de `dominio/` de propósito. A entidade responde às
regras do negócio; o esquema responde ao contrato da API, que muda por outros
motivos — e é onde campo sensível é omitido conforme o papel de quem pede.
"""
