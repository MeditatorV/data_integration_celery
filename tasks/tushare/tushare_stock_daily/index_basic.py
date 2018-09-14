"""
Created on 2018-09-14
@author: yby
@desc    : 2018-09-14
contact author:ybychem@gmail.com
"""
import pandas as pd
import logging
from tasks.backend.orm import build_primary_key
from datetime import date, datetime, timedelta
from tasks.utils.fh_utils import try_2_date, STR_FORMAT_DATE, datetime_2_str, split_chunk, try_n_times
from tasks import app
from sqlalchemy.types import String, Date, Integer
from sqlalchemy.dialects.mysql import DOUBLE
from tasks.backend import engine_md
from tasks.merge.code_mapping import update_from_info_table
from tasks.utils.db_utils import with_db_session, add_col_2_table, alter_table_2_myisam, \
    bunch_insert_on_duplicate_update
from tasks.tushare import pro

DEBUG = False
logger = logging.getLogger()
DATE_BASE = datetime.strptime('2005-01-01', STR_FORMAT_DATE).date()
ONE_DAY = timedelta(days=1)
# 标示每天几点以后下载当日行情数据
BASE_LINE_HOUR = 16
STR_FORMAT_DATE_TS = '%Y%m%d'

INDICATOR_PARAM_LIST_TUSHARE_STOCK_INDEX_BASIC = [
    ('ts_code', String(30)),
    ('name', String(100)),
    ('fullname', String(200)),
    ('market', String(100)),
    ('publisher', String(100)),
    ('index_type', String(100)),
    ('category', String(50)),
    ('base_date', Date),
    ('base_point', DOUBLE),
    ('list_date', Date),
    ('weight_rule', String(200)),
    ('desc', Text),
    ('exp_date', Date),
]
# 设置 dtype
DTYPE_TUSHARE_STOCK_INDEX_BASIC = {key: val for key, val in INDICATOR_PARAM_LIST_TUSHARE_STOCK_INDEX_BASIC}


@try_n_times(times=5, sleep_time=0, logger=logger, exception=Exception, exception_sleep_time=60)
def invoke_index_basic(market):
    invoke_index_basic = pro.index_basic(market=market,fields=fields)
    return invoke_index_basic


@app.task
def import_tushare_INDEX_BASIC(chain_param=None):
    """
    插入股票日线数据到最近一个工作日-1。
    如果超过 BASE_LINE_HOUR 时间，则获取当日的数据
    :return:
    """
    table_name = 'tushare_stock_index_basic'
    logging.info("更新 %s 开始", table_name)

    has_table = engine_md.has_table(table_name)
    # 下面一定要注意引用表的来源，否则可能是串，提取混乱！！！比如本表是tushare_INDEX_BASIC，所以引用的也是这个，如果引用错误，就全部乱了l
    if has_table:
        sql_str = """
               select cal_date            
               FROM
                (
                 select * from tushare_trade_date trddate 
                 where( cal_date>(SELECT max(trade_date) FROM {table_name} ))
               )tt
               where (is_open=1 
                      and cal_date <= if(hour(now())<16, subdate(curdate(),1), curdate()) 
                      and exchange_id='SSE') """.format(table_name=table_name)
    else:
        sql_str = """
               SELECT cal_date FROM tushare_trade_date trddate WHERE (trddate.is_open=1 
            AND cal_date <= if(hour(now())<16, subdate(curdate(),1), curdate()) 
            AND exchange_id='SSE') ORDER BY cal_date"""
        logger.warning('%s 不存在，仅使用 tushare_stock_info 表进行计算日期范围', table_name)

    with with_db_session(engine_md) as session:
        # 获取交易日数据
        table = session.execute(sql_str)
        trddate = list(row[0] for row in table.fetchall())

    fields='ts_code','name','fullname','market','publisher','index_type','category','base_date','base_point','list_date','weight_rule','desc','exp_date'
    market_list(['MSCI','CSI','SSE','SZSE','CICC','SW','CNI','OTH'])

    try:
        for mkt in market_list:
            trade_date = datetime_2_str(trddate[i], STR_FORMAT_DATE_TS)
            data_df = invoke_index_basic(market=mkt, fields=fields)
            if len(data_df) > 0:
                data_count = bunch_insert_on_duplicate_update(data_df, table_name, engine_md, DTYPE_TUSHARE_STOCK_INDEX_BASIC)
                logging.info("%s更新 %s 结束 %d 条信息被更新", mkt, table_name, data_count)
            else:
                logging.info("无数据信息可被更新")
    finally:
        if not has_table and engine_md.has_table(table_name):
            alter_table_2_myisam(engine_md, [table_name])
            # build_primary_key([table_name])
            create_pk_str = """ALTER TABLE {table_name}
                CHANGE COLUMN `ts_code` `ts_code` VARCHAR(20) NOT NULL FIRST,
                CHANGE COLUMN `trade_date` `trade_date` DATE NOT NULL AFTER `ts_code`,
                ADD PRIMARY KEY (`ts_code`, `trade_date`)""".format(table_name=table_name)
            with with_db_session(engine_md) as session:
                session.execute(create_pk_str)
            logger.info('%s 表 `ts_code`, `trade_date` 主键设置完成', table_name)

if __name__ == "__main__":
    # DEBUG = True
    import_tushare_index_basic()

#下面代码是生成fields和par的

# sub=pd.read_excel('tasks/tushare/tushare_fina_reports/fina_indicator.xlsx',header=0)[['code','types']]
# for a, b in [tuple(x) for x in sub.values]:
#     print("('%s', %s)," % (a, b))
#     # print("'%s'," % (a))