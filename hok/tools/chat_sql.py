"""Pure validation and normalization for model-written PostgreSQL reads.

Database permissions and READ ONLY transactions are independent enforcement
layers. This module never opens a connection or touches the filesystem.
"""

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel, SqlglotError
from sqlglot.optimizer.scope import traverse_scope

from ..chat_sql_schema import CHAT_SQL_COLUMN_USAGE, CHAT_SQL_TABLES


# Names here are sqlglot's canonical names, not arbitrary server functions.
SAFE_FUNCTIONS = frozenset("""
    ABS ACOS ASIN ATAN ATAN2 AVG AND ARRAY ARRAY_AGG ARRAY_SIZE BOOL_AND BOOL_OR
    CASE CAST CEIL COALESCE CONCAT CONCAT_WS CORR COS COUNT COVAR_POP COVAR_SAMP
    CUME_DIST CURRENT_DATE CURRENT_TIMESTAMP DATE DATE_ADD DATE_DIFF DATE_TRUNC
    DENSE_RANK EXP EXPLODE EXTRACT FIRST_VALUE FLOOR GREATEST IF JSON_EXTRACT
    JSON_EXTRACT_SCALAR JSONB_EXTRACT JSONB_EXTRACT_SCALAR LAG LAST_VALUE LEAD
    LEAST LEFT LENGTH LN LOG LOWER MAX MIN MOD NTH_VALUE NTILE NULLIF
    OR PERCENT_RANK PERCENTILE_CONT PERCENTILE_DISC POW POWER RANK REGEXP_LIKE REGEXP_I_LIKE
    REGEXP_REPLACE REGEXP_SPLIT REPLACE RIGHT ROUND ROW_NUMBER SIGN SIN SQRT
    STDDEV STDDEV_POP STDDEV_SAMP STRING_AGG SUBSTRING SUM TAN TIMESTAMP_TRUNC
    TIME_TO_STR TRIM TRUNC UNNEST UNIX_TO_TIME UPPER VARIANCE VAR_POP VAR_SAMP
""".split())

SAFE_ANONYMOUS_FUNCTIONS = frozenset("""
    json_array_length jsonb_array_length json_array_elements jsonb_array_elements
    json_array_elements_text jsonb_array_elements_text json_each jsonb_each
    json_each_text jsonb_each_text json_object_keys jsonb_object_keys
    json_typeof jsonb_typeof json_build_object jsonb_build_object
    json_build_array jsonb_build_array json_agg jsonb_agg json_object_agg jsonb_object_agg
    json_extract_path jsonb_extract_path json_extract_path_text jsonb_extract_path_text
    array_length array_position cardinality to_char to_date to_timestamp
    date_part date_trunc string_agg regexp_replace regexp_match regexp_matches
    split_part strpos width_bucket
""".split())

SAFE_TABLE_FUNCTIONS = frozenset("""
    json_array_elements jsonb_array_elements json_array_elements_text
    jsonb_array_elements_text json_each jsonb_each json_each_text jsonb_each_text
    json_object_keys jsonb_object_keys
""".split())

SAFE_CAST_TYPES = frozenset("""
    BIGINT INT SMALLINT TINYINT FLOAT DOUBLE DECIMAL BOOLEAN TEXT VARCHAR CHAR
    DATE TIMESTAMP TIMESTAMPTZ INTERVAL JSON JSONB ARRAY UNKNOWN
""".split())

FORBIDDEN_COLUMNS = frozenset({
    "source_path", "tableoid", "xmin", "xmax", "cmin", "cmax", "ctid", "oid",
})


class ChatSQLValidationError(ValueError):
    """A SQL query cannot be executed by the chat reader."""


def _function_name(node):
    return node.name.lower() if isinstance(node, exp.Anonymous) else node.sql_name()


def _validate_column_usage(column, source, column_usage):
    """Enforce declarative business-column capabilities for a physical source."""
    rule = column_usage.get(f"{source.name.lower()}.{column.name.lower()}")
    if not rule:
        return
    invalid_usage = (
        (not rule.get("allow_predicate", True)
         and (column.find_ancestor(exp.Predicate) or column.find_ancestor(exp.Join)))
        or (not rule.get("allow_grouping", True) and column.find_ancestor(exp.Group))
        or (not rule.get("allow_ordering", True) and column.find_ancestor(exp.Order))
    )
    if invalid_usage:
        raise ChatSQLValidationError(
            f"字段仅供展示，不能参与过滤、关联、分组或排序：{source.name}.{column.name}；{rule['rule']}"
        )


def validate_readonly_sql(sql, params=None, max_sql_chars=20000, *,
                          allowed_tables=None, column_usage=None,
                          schema_tool_name="get_game_database_schema"):
    """Return canonical SQL after validating one bounded analytical read.

    Optional parameters use ``:name`` and a dictionary of JSON scalar values.
    Values become AST literals, never SQL string interpolation.
    """
    allowed_tables = CHAT_SQL_TABLES if allowed_tables is None else allowed_tables
    column_usage = CHAT_SQL_COLUMN_USAGE if column_usage is None else column_usage
    if not isinstance(allowed_tables, dict) or not allowed_tables:
        raise ChatSQLValidationError("SQL表白名单未配置")
    if not isinstance(sql, str) or not sql.strip():
        raise ChatSQLValidationError("sql 必须是非空的 PostgreSQL SELECT")
    if len(sql) > max_sql_chars:
        raise ChatSQLValidationError(f"SQL 超过 {max_sql_chars} 字符上限")
    try:
        statements = parse(sql, read="postgres", error_level=ErrorLevel.RAISE)
    except SqlglotError as exc:
        raise ChatSQLValidationError("PostgreSQL SQL 解析失败；请检查语法") from exc
    if len(statements) != 1 or statements[0] is None:
        raise ChatSQLValidationError("每次仅允许一条 SELECT/CTE；禁止多语句")
    query = statements[0]
    if not isinstance(query, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise ChatSQLValidationError("仅允许 SELECT 或 WITH ... SELECT")

    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ChatSQLValidationError("params 必须为名称到JSON标量的对象")
    placeholders = list(query.find_all(exp.Placeholder))
    parameter_names = {node.name for node in placeholders}
    if parameter_names != set(params) or any(not name for name in parameter_names):
        raise ChatSQLValidationError("命名参数必须与SQL中的 :name 占位符一一对应")
    for placeholder in placeholders:
        value = params[placeholder.name]
        if value is not None and not isinstance(value, (str, bool, int, float)):
            raise ChatSQLValidationError("SQL参数只接受字符串、数字、布尔或null")
        placeholder.replace(exp.convert(value))

    for node in query.walk():
        if isinstance(node, (exp.DDL, exp.DML, exp.Command, exp.Into, exp.Lock, exp.Operator, exp.TableSample,
                             exp.Dot, exp.Collate, exp.Parameter, exp.SessionParameter)):
            raise ChatSQLValidationError(f"SQL不允许此操作：{type(node).__name__}")
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise ChatSQLValidationError("不允许递归CTE")
        if isinstance(node, exp.CTE) and not isinstance(
            node.this, (exp.Select, exp.Union, exp.Intersect, exp.Except)
        ):
            raise ChatSQLValidationError("CTE内只允许SELECT")
        if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
            raise ChatSQLValidationError("请显式列出所需列；只有COUNT(*)允许星号")
        if isinstance(node, exp.Column):
            if node.name.lower() in FORBIDDEN_COLUMNS or node.catalog:
                raise ChatSQLValidationError("该列不可供聊天查询")
            if node.db and node.db != "hok":
                raise ChatSQLValidationError("只能访问hok业务schema")
        if isinstance(node, exp.DataType):
            if getattr(node.this, "value", str(node.this)) not in SAFE_CAST_TYPES or node.args.get("kind"):
                raise ChatSQLValidationError("只允许普通数字、文本、日期及JSON类型转换")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            allowed = SAFE_ANONYMOUS_FUNCTIONS if isinstance(node, exp.Anonymous) else SAFE_FUNCTIONS
            if name not in allowed:
                raise ChatSQLValidationError(f"函数不在只读分析白名单：{name}")

    # Resolve CTEs per lexical scope; a same-named CTE in an unrelated subquery
    # must never authorize an otherwise forbidden physical table.
    try:
        for scope in traverse_scope(query):
            for table in scope.tables:
                if not isinstance(table.this, exp.Identifier):
                    if not isinstance(table.this, exp.Anonymous) or table.this.name.lower() not in SAFE_TABLE_FUNCTIONS:
                        raise ChatSQLValidationError("不允许此类表函数")
                    if table.db or table.catalog:
                        raise ChatSQLValidationError("表函数不可指定schema")
                    continue
                if not table.db and not table.catalog and table.name in scope.cte_sources:
                    continue
                if table.catalog or table.db not in ("", "hok") or table.name not in allowed_tables:
                    raise ChatSQLValidationError(f"表不在允许的业务表中：{table.name}")
                table.set("db", exp.to_identifier("hok"))

            physical_sources = {
                alias: source for alias, source in scope.sources.items()
                if isinstance(source, exp.Table) and source.name.lower() in allowed_tables
            }

            def physical_source(column):
                source = physical_sources.get(column.table) if column.table else None
                if source is None and not column.table and len(physical_sources) == 1:
                    source = next(iter(physical_sources.values()))
                return source

            for column in scope.columns:
                source = physical_source(column)
                if source is not None and column.name.lower() not in allowed_tables[source.name.lower()]["columns"]:
                    qualifier = column.table or source.alias_or_name
                    raise ChatSQLValidationError(
                        f"列不在已披露schema中：{qualifier}.{column.name}；请按{schema_tool_name}返回的列改写"
                    )
                if source is not None:
                    _validate_column_usage(column, source, column_usage)

            # sqlglot treats an unqualified ORDER BY name as an output alias and
            # omits it from scope.columns.  When the scope has one physical
            # source, still enforce that source column's declared capability.
            order = scope.expression.args.get("order")
            if order is not None:
                for column in order.find_all(exp.Column):
                    source = physical_source(column)
                    if source is not None:
                        _validate_column_usage(column, source, column_usage)
    except SqlglotError as exc:
        raise ChatSQLValidationError("SQL来源解析失败") from exc

    output_names = [name.lower() for name in query.named_selects if name and name != "*"]
    duplicate_names = sorted({name for name in output_names if output_names.count(name) > 1})
    if duplicate_names:
        raise ChatSQLValidationError("结果列名重复；请为这些字段添加唯一别名：" + ", ".join(duplicate_names))

    # Re-serialization discards unsupported original syntax. Never execute the
    # original model string after validating a different representation.
    try:
        normalized = query.sql(dialect="postgres", unsupported_level=ErrorLevel.RAISE)
    except SqlglotError as exc:
        raise ChatSQLValidationError("SQL含不支持的PostgreSQL表达式") from exc
    if len(normalized) > max_sql_chars:
        raise ChatSQLValidationError("展开参数后的SQL超过长度上限")
    return normalized
