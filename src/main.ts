import { DateTime } from 'luxon';
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

  const { records } = await getAttendanceRecordList(cookie, yearmo);
  for (const record of records) {
    if (record.situation != IAttendanceRecordSituation.WARNING) {
      continue;
    }

    const time = DateTime.fromSeconds(record.time);
    console.log(`+ ${time.toFormat('yyyy-LL-dd')}`);

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

    if (bdkBegin) {
      console.log(`  上班: ${chalk.yellow(bdkBegin)}（补签）`);
    } else if (!timeBegin || !timeBegin.clockTime) {
      console.log(`  上班: ${chalk.white.bgRed('缺 卡')}`);
    } else if (timeBegin.statusDesc) {
      console.log(`  上班: ${chalk.white.bgRed(timeBegin.clockTime)} ${timeBegin.statusDesc}`);
    } else {
      console.log(`  上班: ${chalk.green(timeBegin.clockTime)}`);
    }

    if (bdkEnd) {
      console.log(`  下班: ${chalk.yellow(bdkEnd)}（补签）`);
    } else if (!timeEnd || !timeEnd.clockTime) {
      console.log(`  下班: ${chalk.white.bgRed('缺 卡')}`);
    } else if (timeEnd.statusDesc) {
      console.log(`  下班: ${chalk.white.bgRed(timeEnd.clockTime)} ${timeEnd.statusDesc}`);
    } else {
      console.log(`  下班: ${chalk.green(timeEnd.clockTime)}`);
    }
  }

})();
