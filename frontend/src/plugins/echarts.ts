/** ECharts 按需注册（雷达 + 折线），vue-echarts 组件统一从这里引入。 */

import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, RadarChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, RadarChart, LineChart, GridComponent, TooltipComponent, LegendComponent])

export default VChart
