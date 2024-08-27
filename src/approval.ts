import { DateTime, DateObjectUnits } from 'luxon';
import Table from 'cli-table3';
import chalk from 'chalk';
import pressAnyKey from 'press-any-key';

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
  getMyApprovalList,
  batchProcessStep
} from './api';

const HOUR_START = 10;
const HOUR_END = 19;

(async () => {

  const args = process.argv.slice(2);

  if (args.length != 1) {
    console.log('Usage: autobdk $COOKIE');
    return process.exit();
  }

  const [cookie] = args;

  console.log('1. 正在获取数据…');

  const { approvalIds } = await getMyApprovalList(cookie);

  const bukaList = approvalIds.filter(item => item.flowType === 6)

  if (bukaList.length == 0) {
    console.log('没有需要处理的考勤');
    return process.exit();
  }

  console.log(`共有${bukaList.length}条考勤需要处理`);
  console.log('');

  console.log('2. 即将批量处理:');
  console.log('');
  
  await pressAnyKey('按任意键继续…');

  console.log('3. 正在处理…');
  console.log('');

  let hasMore = true;
  const statistics: {
    [key: string]: number;
  } = {};


  while(hasMore) {
    const { approvalList } = await getMyApprovalList(cookie);
    if (approvalList.find(item => item.flowType === 6)) {
      hasMore = true;
    } else {
      hasMore = false;
    }
    if (hasMore) {
      const batchForm = {
        process_step_ids: approvalList.filter(item => item.flowType === 6).map(item => {
          if (statistics[item.title] >= 0) {
            statistics[item.title] += 1;
          } else {
            statistics[item.title] = 1;
          }
          return item.processStepId;
        }).join(','),
        sids: bukaList.filter(item => item.flowType === 6).map(item => item.sid).join(','),
        approve_status: 1,
        remark: '同意',
        sign: ''
      }
      await batchProcessStep(cookie, batchForm);
    }
  }

  const table = new Table({
    head: ['人员', '数量'],
    colWidths: [30, 30],
  });

  for (let i in statistics) {
    table.push([
      chalk.white(i),
      statistics[i]
    ]);
  }

  

  console.log(table.toString());
  console.log('');

  console.log('4. 完成');

})();
