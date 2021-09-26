import http from 'got';

const XRXS_URL = 'https://e.xinrenxinshi.com';

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

export interface IAttendanceRecord {
  bdkErrorMessage: null;
  bdkStatus: number;
  isFinish: number;
  isShowClockTime: number;
  signTimeList: {
    clockTime: string;  // "12:45"
    rangeId: string;
    rangeName: '上班' | '下班';
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
