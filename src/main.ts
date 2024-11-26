import { DateTime, DateObjectUnits } from 'luxon';
import Table from 'cli-table3';
import chalk from 'chalk';
import pressAnyKey from 'press-any-key';
import { setTimeout } from 'timers/promises';

import {
  IAttendanceRecordSituation,
  IAttendanceRecord,
  IAttendanceClockType,
  IAttendanceApproval,
  getAttendanceRecordList,
  getAttendanceRecordByDate,
  getApproveBdkFlow,
  newSignAgain,
  startAttendanceApproval,
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

  const approving: {
    time: DateTime,
    clockType: IAttendanceClockType,
    rangeId: string;
  }[] = [];

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

    if (!timeBegin || !timeEnd) {
      continue;
    }

    if (!bdkBegin && (!timeBegin.clockTime || timeBegin.statusDesc)) {
      approving.push({
        time: time.set({ hour: HOUR_START, minute: 0 }),
        clockType: timeBegin.clockAttribution,
        rangeId: timeBegin.rangeId,
      });
    }

    if (!bdkEnd && (!timeEnd.clockTime || timeEnd.statusDesc)) {
      const actualBegin = timeBegin.clockTime
        ? DateTime.fromFormat(timeBegin.clockTime, 'HH:mm')
        : null;

      const values: DateObjectUnits = (actualBegin && actualBegin.hour >= HOUR_END)
        ? { hour: actualBegin.hour, minute: actualBegin.minute + 1 }
        : { hour: HOUR_END, minute: 0 };

      approving.push({
        time: time.set(values),
        clockType: timeEnd.clockAttribution,
        rangeId: timeEnd.rangeId,
      });
    }
  }

  console.log(table.toString());
  console.log('');

  if (approving.length == 0) {
    console.log('没有需要补签的考勤');
    return process.exit();
  }

  console.log('2. 即将发起下列补签:');
  for (const app of approving) {
    console.log(`   * ${IAttendanceClockType[app.clockType]}: ${app.time.toFormat('LL-dd HH:mm')}`);
  }
  console.log('');

  await pressAnyKey('按任意键继续…');

  console.log('3. 正在补签…');
  const sign = await newSignAgain(cookie);
  for (const app of approving) {
    const request: IAttendanceApproval = {
      flow_type: sign.flow_type,
      flowSettingId: sign.flowSettingId,
      departmentId: sign.departmentList[0].departmentId,
      date: `${app.time.set({ hour: 0, minute: 0 }).toSeconds()}`,
      start_date: app.time.toFormat('yyyy-LL-dd HH:mm'),
      timeRangeId: app.rangeId,
      bdkDate: app.time.toFormat('yyyy-LL-dd'),
      clockType: app.clockType,
    };
    for (let i = 0; i < 5; i++) {
      const result = await startAttendanceApproval(cookie, request);
      const resultText = result ? chalk.red(result) : chalk.green('成功');
      console.log(`   * ${IAttendanceClockType[app.clockType]}: ${app.time.toFormat('LL-dd HH:mm')} ... ${resultText}`);
      if (!result?.includes('重复提交')) {
        break;
      }
    }
    await setTimeout(10 * 1000);
  }
  console.log('');

  console.log('4. 完成');

})();
