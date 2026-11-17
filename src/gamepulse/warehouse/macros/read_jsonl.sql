{#
  Read newline-delimited JSON files with a fixed set of columns.

  This is the only place that knows the raw data lives in JSON files. Columns
  are spelled out so a missing key becomes NULL instead of changing the
  schema, and a half-written last line (a collector was writing) is skipped.
  When no file matches yet, the result is an empty relation with the same
  columns, so a source that has not been collected does not break the build.

  `columns` maps a column name to its DuckDB type. The file path is available
  as the column `filename`.
#}
{% macro read_jsonl(glob, columns) %}
    {%- set found = true -%}
    {%- if execute -%}
        {%- set found = run_query("select count(*) from glob('" ~ glob ~ "')").columns[0].values()[0] > 0 -%}
    {%- endif -%}
    {%- if found -%}
    read_json(
        '{{ glob }}',
        format = 'newline_delimited',
        ignore_errors = true,
        filename = true,
        columns = {
            {%- for name, type in columns.items() %}
            '{{ name }}': '{{ type }}'{{ "," if not loop.last }}
            {%- endfor %}
        }
    )
    {%- else -%}
    (
        select
            {%- for name, type in columns.items() %}
            cast(null as {{ type }}) as "{{ name }}",
            {%- endfor %}
            cast(null as varchar) as filename
        where false
    )
    {%- endif -%}
{% endmacro %}

{# 'github' for files pulled from the data branch, 'local' for this machine's own. #}
{% macro collected_by(filename) -%}
    case when parse_filename({{ filename }}) like 'gh-%' then 'github' else 'local' end
{%- endmacro %}

{# Collectors write UTC timestamps as 2026-11-17T09:00:55Z. #}
{% macro utc_timestamp(column) -%}
    try_strptime({{ column }}, '%Y-%m-%dT%H:%M:%SZ')
{%- endmacro %}
