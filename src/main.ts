import { DateTime } from 'luxon';
import * as Table from 'cli-table3';
import * as chalk from 'chalk';

import {
  IAttendanceRecordSituation,
  IAttendanceRecord,
  getAttendanceRecordList,
  getAttendanceRecordByDate,
  getApproveBdkFlow,
} from './api';

const HOUR_START = 10;
const HOUR_END = 19;

(async () => {

  const args = process.argv.slice(2);

  if (args.length != 2) {
    console.log('Usage: autobdk $COOKIE 202109');
    return process.exit();
  }

  const [cookie, yearmo] = args;

  console.log('1. 正在获取数据…');
  const table = new Table({
    head: ['日期', '上班', '下班'],
    colWidths: [10, 30, 30],
  });

  const { records } = await getAttendanceRecordList(cookie, yearmo);
  for (const record of records) {
    if (record.situation != IAttendanceRecordSituation.WARNING) {
      continue;
    }

    const time = DateTime.fromSeconds(record.time);

    let timeBegin: IAttendanceRecord['signTimeList'][0] | null = null;
    let timeEnd: IAttendanceRecord['signTimeList'][0] | null = null;

    const { signTimeList } = await getAttendanceRecordByDate(cookie, time.toFormat('yyyyLLdd'));
    for (const signTime of signTimeList) {
      if (signTime.rangeName == '上班') {
        timeBegin = signTime;
      } else if (signTime.rangeName == '下班') {
        timeEnd = signTime;
      }
    }

    let bdkBegin: string | null = null;
    let bdkEnd: string | null = null;

    const approves = await getApproveBdkFlow(cookie, `${record.time}`);
    for (const approve of approves) {
      const time = DateTime.fromSeconds(approve.startDate);
      if (time.hour <= HOUR_START) {
        bdkBegin = time.toFormat('HH:mm');
      } else if (time.hour >= HOUR_END) {
        bdkEnd = time.toFormat('HH:mm');
      }
    }

    function getTimeString(record: IAttendanceRecord['signTimeList'][0] | null, bdk: string | null): string {
      if (bdk) {
        return `${chalk.yellow(bdk)} ${chalk.gray('补签')}`;
      } else if (!record || !record.clockTime) {
        return `${chalk.white.bgRed('缺 卡')}`;
      } else if (record.statusDesc) {
        return `${chalk.white.bgRed(record.clockTime)} ${chalk.white(record.statusDesc)}`;
      } else {
        return `${chalk.green(record.clockTime)}`;
      }
    }

    table.push([
      chalk.white.bold(time.toFormat('LL-dd')),
      getTimeString(timeBegin, bdkBegin),
      getTimeString(timeEnd, bdkEnd),
    ]);
  }

  console.log(table.toString());

})();
