(function(root){
  const runtimeFields=['prompt_id','run_dir','status','error','results'];
  const clone=value=>value===undefined?undefined:JSON.parse(JSON.stringify(value));
  const projectKey=project=>typeof project?.project_dir==='string'&&project.project_dir.trim()?project.project_dir.trim().replace(/\\/g,'/').replace(/\/+$/,'').toLowerCase():'';

  function mergeImportedProject(current,imported){
    if(!imported||typeof imported!=='object'||!Array.isArray(imported.shots))throw new Error('导入项目的 shots 必须是数组');
    const importedIds=new Set();
    imported.shots.forEach((shot,index)=>{
      const plain=shot!==null&&typeof shot==='object'&&!Array.isArray(shot)&&(Object.getPrototypeOf(shot)===Object.prototype||Object.getPrototypeOf(shot)===null);
      if(!plain)throw new Error(`导入项目的第 ${index+1} 个片段必须是对象`);
      if(typeof shot.id!=='string'||!shot.id.trim())throw new Error(`导入项目的第 ${index+1} 个片段缺少有效 id`);
      if(importedIds.has(shot.id))throw new Error(`导入项目包含重复片段 id：${shot.id}`);
      importedIds.add(shot.id);
    });
    const currentProject=current&&typeof current==='object'?current:{};
    const currentShots=Array.isArray(currentProject.shots)?currentProject.shots:[];
    const currentById=new Map(currentShots.map(shot=>[shot&&shot.id,shot]));
    const currentProjectKey=projectKey(currentProject),importedProjectKey=projectKey(imported);
    const sameProject=!currentProjectKey||!importedProjectKey||currentProjectKey===importedProjectKey;
    const merged=clone(imported);
    if(!(typeof imported.project_dir==='string'&&imported.project_dir.trim()))merged.project_dir=clone(currentProject.project_dir);
    merged.shots=imported.shots.map(importedShot=>{
      const shot=clone(importedShot);
      const existing=importedShot&&currentById.get(importedShot.id);
      if(!existing||!sameProject||Array.isArray(importedShot.results)&&importedShot.results.length)return shot;
      runtimeFields.forEach(field=>{
        if(Object.prototype.hasOwnProperty.call(existing,field))shot[field]=clone(existing[field]);
        else delete shot[field];
      });
      return shot;
    });
    return merged;
  }

  const api={mergeImportedProject};
  root.Ref2VAProjectMerge=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
