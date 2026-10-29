import collections, getpass, oracledb

DSN = "127.0.0.1:31521/orclpdbsvc"
SQL = """select sys_context('USERENV','INSTANCE_NAME'),
                sys_context('USERENV','SERVER_HOST'),
                sys_context('USERENV','CON_NAME') from dual"""

pw = getpass.getpass("SYSTEM password: ")
seen = collections.Counter()
for n in range(1, 11):
    with oracledb.connect(user="system", password=pw, dsn=DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
            inst, host, con = cur.fetchone()
    seen[inst] += 1
    print(f"{n:2}  {inst:9} {host:11} {con}")
print("oracledb", oracledb.__version__, "thin mode:", oracledb.is_thin_mode())
print("connections per instance:", dict(seen))
