import http from 'got';

const XRXS_URL = 'https://e.xinrenxinshi.com';

interface IEnvelope<T> {
  code: number;
  data: T;
  message: string;
  status: boolean;
}

interface IEnvelope<T> {
  code: number;
  data: T;
  message: string;
  status: boolean;
}

export enum IAttendanceRecordMonthStatus {
  CURRENT = 0,
  NOT_CURRENT = -1,
}

export enum IAttendanceRecordSituation {
  NORMAL = 0,
  WARNING = -1,
}

interface IAttendanceRecordList {
  attandanceArchive: {
    begin: string;
    end: string;
    yearmo: string;
  };
  attendanceStatistics: {
    absentNum: number;
    lateNum: number;
    leaveEarlyNum: number;
    leaveOrOut: number;
    noWorkdayNum: number;
  };
  bdkUrl: string;
  isShowClockTime: boolean;
  records: {
    clockName: string | null;
    clockSettingId: number;
    containsData: number;
    date: number;
    detailInfo: null;
    isClocking: number;
    isToday: number;
    isWorkday: number;
    lunarShow: string | null;
    monthStatus: IAttendanceRecordMonthStatus;
    situation: IAttendanceRecordSituation;
    time: number;
  }[];
  schedulingType: number;
  showClockTime: boolean;
}

interface IApprovalList {
  approvalIds: {
    flowType: number; 
    processId: number;
    sid: string;
  }[]
  approvalList: {
    sid: string;
    processStepId: string;
    flowType: number;
    title: string;
  }[]
}

interface IBatchForm {
  process_step_ids: string;
  sids: string;
  approve_status: number;
  remark: string;
  sign: string;
}

export async function getAttendanceRecordList(cookie: string, yearmo = ''): Promise<IAttendanceRecordList> {
  const { data } = await http.post(`${XRXS_URL}/attendance/ajax-get-attendance-record-list`, {
    headers: {
      Cookie: cookie,
    },
    form: {
      yearmo,
    },
  }).json() as IEnvelope<IAttendanceRecordList>;
  return data;
}

export async function getMyApprovalList(cookie: string): Promise<IApprovalList> {
  const { data } = await http.post(`${XRXS_URL}/flow/ajax-get-my-approval-list`, {
    headers: {
      Cookie: cookie,
    },
    form: {
      data: JSON.stringify({"isProcessed":0,"page":1,"pn":10,"sortType":-1,"addtime":-1,"customAddtime":"","status":-1,"flowType":-1,"yemo":"","keyWord":""})
    },
  }).json() as IEnvelope<IApprovalList>;
  return data;
}

export async function batchProcessStep(cookie: string, form: IBatchForm): Promise<string> {
  const { message } = await http.post(`${XRXS_URL}/flow/ajax-batch-process-step`, {
    headers: {
      Cookie: cookie,
    },
    form: form,
  }).json() as IEnvelope<IApprovalList>;
  return message;
}

export enum IAttendanceClockType {
  上班 = 1,
  下班 = 2,
}

export interface IAttendanceRecord {
  bdkErrorMessage: null;
  bdkStatus: number;
  isFinish: number;
  isShowClockTime: number;
  signTimeList: {
    clockAttribution: IAttendanceClockType;
    clockTime: string;  // "12:45"
    rangeId: string;
    rangeName: keyof typeof IAttendanceClockType;
    statusDesc: string;  // 空字符串时表示没异常
  }[];
  situationDesc: null;
  timeRanges: {
    startingTime: string;  // "09:00"
    closingTime: string;
  }[];
}

// date: 20210826
export async function getAttendanceRecordByDate(cookie: string, date: string): Promise<IAttendanceRecord> {
  const { data } = await http.post(`${XRXS_URL}/attendance/ajax-get-attendance-record-by-date`, {
    headers: {
      Cookie: cookie,
    },
    form: {
      date,
    },
  }).json() as IEnvelope<IAttendanceRecord>;
  return data;
}

interface IApproveBdkFlow {
  flowSid: string;
  flowTypeName: string;
  isFinish: number;
  startDate: number;  // 1630407600
}

// date: 1630252800
export async function getApproveBdkFlow(cookie: string, date: string): Promise<IApproveBdkFlow[]> {
  const { data } = await http.post(`${XRXS_URL}/attendance/ajax-get-approve-bdk-flow`, {
    headers: {
      Cookie: cookie,
    },
    form: {
      date,
    },
  }).json() as IEnvelope<IApproveBdkFlow[]>;
  return data;
}

interface INewSignAgain {
  departmentList: {
    departmentId: string;
    departmentName: string;
  }[];
  flowSettingId: number;
  flow_type: number;  // 6
  flow_type_desc: string;  // "补卡"
}

export async function newSignAgain(cookie: string): Promise<INewSignAgain> {
  const { data } = await http.post(`${XRXS_URL}/attendance/ajax-new-sign-again`, {
    headers: {
      Cookie: cookie,
    },
  }).json() as IEnvelope<INewSignAgain>;
  return data;
}

export interface IAttendanceApproval {
  flow_type: number;
  flowSettingId: number;
  departmentId: string;
  date: string;  // "1630425600"
  start_date: string;  // "2021-09-01 10:00"
  timeRangeId: string;
  bdkDate: string;  // "2021-09-01"
  clockType: IAttendanceClockType,
}

export async function startAttendanceApproval(cookie: string, approval: IAttendanceApproval): Promise<void> {
  const data = JSON.stringify({
    flow_type: approval.flow_type,
    flowSettingId: approval.flowSettingId,
    departmentId: approval.departmentId,
    isClocking: 0,
    date: approval.date,
    start_date: approval.start_date,
    reason: '',
    image_path: '',
    timeRangeId: approval.timeRangeId,
    bdkDate: approval.bdkDate,
    clockType: approval.clockType,
    rangeModels: [],
    custom_field: "[]"
  });
  
  const MAX_RETRIES = 10; // 最大重试次数
  const SLEEP_TIME = 1000; // 1s
  let retries = 0;
  let success = false;
  let res: {
    status?: boolean;
  };

  while (!success && retries < MAX_RETRIES) {
    try {
      res = await http.post(`${XRXS_URL}/attendance/ajax-start-attendance-approval`, {
        headers: {
          Cookie: cookie,
        },
        form: {
          data,
        },
      }).json();

      if (res?.status) {
        success = true;
      } else {
        retries++;
        console.log(`重试中... 次数： ${retries}`);
        // 加入 1 秒的延迟
        await new Promise(resolve => setTimeout(resolve, SLEEP_TIME)); // 1秒的延迟
      }
    } catch (error) {
      console.error("请求失败:", error);
      retries++;
      // 加入 1 秒的延迟
      await new Promise(resolve => setTimeout(resolve, SLEEP_TIME)); // 1秒的延迟
    }
  }

  if (!success) {
    console.error(`重试了${MAX_RETRIES}次都失败，shit!`);
  } else {
    console.log("打卡成功。");
  }

}
